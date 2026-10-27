#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
poly_wav.py — パラWAV → Polyphonic WAV (Poly WAV) 結合変換ツール

ZOOM H6essential (H6e) / H5 / H4e / F-series 等のフィールドレコーダーが
テイクフォルダ内に分離保存した個別トラックWAV

    ZOOM0001/
      ├ ZOOM0001_Tr1.WAV   (mono)
      ├ ZOOM0001_Tr2.WAV   (mono)
      ├ ZOOM0001_Tr3.WAV   (mono)
      ├ ZOOM0001_Tr4.WAV   (mono)
      ├ ZOOM0001_LR.WAV    (stereo: XYマイク等)
      └ ZOOM0001_Mix.WAV   (2MIX … 既定では除外)

を、Pro Tools 等のDAWで1ファイルとして扱える
マルチチャンネル Poly WAV (BWF) に括り出します。

■ 精度について (最重要)
  波形はデコード/再量子化を一切しません。各入力ファイルの data chunk を
  「サンプル(バイト列)の列」としてそのままフレーム単位でインターリーブする
  ため、32-bit float / 24-bit / 16-bit / 32-bit int のいずれでも
  ビットパーフェクト (量子化誤差なし・クリッピングなし) です。

■ 依存ライブラリ
  必須: なし (Python 3.8+ 標準ライブラリのみ)
        → Mac 標準の python3 はもちろん、iPhone の a-Shell / Pyto、
          Android の Pydroid 3 / Termux でもそのまま動きます。
  任意: numpy があれば高速化されます (無くても動作します)。

■ 使い方
  # テイクフォルダ1つ
  python3 poly_wav.py /path/to/ZOOM0001

  # 複数テイクが入った親フォルダ (配下を再帰スキャン)
  python3 poly_wav.py /path/to/SDCARD_ROOT

  # ドラッグ&ドロップ: フォルダをスクリプト/一発起動.command に落とすだけ
  python3 poly_wav.py ZOOM0001 ZOOM0002

  # 主なオプション
  --include-mix    *_Mix.WAV (2MIX) も含める (既定は除外)
  --lr-first       LR/XY トラックを先頭に置く (既定は Tr の後ろ)
  --outdir DIR     出力先フォルダを指定
  --inplace        テイクフォルダの中に出力する
  --overwrite      既存の出力ファイルを上書きする
  --dry-run        変換せずチャンネル割当だけ表示する

■ メタデータ
  * bext (BWF) chunk: 先頭トラックのものをそのまま継承
    (TimeReference=タイムコード開始点などはテイク共通のため)
  * iXML chunk: TRACK_LIST を出力チャンネル数に合わせて再構築し、
    各トラック名 (入力 iXML の <NAME> があればそれ、無ければ Tr1/LR 等) を引き継ぐ
  * フォーマットが多ch/ float の場合は WAVE_FORMAT_EXTENSIBLE で書き出す
  * 出力が 4GB 超になりそうな場合は RF64 (ds64) で書き出す
"""

from __future__ import annotations

import argparse
import copy
import re
import struct
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

try:
    import numpy as np  # 任意: ある環境では高速パスを使う
except Exception:  # pragma: no cover
    np = None

# Windows コンソール (cp932等) で絵文字/日本語が化けて落ちないようにする
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

# ----------------------------------------------------------------------------
# 定数
# ----------------------------------------------------------------------------
SPEAKER_POSITIONS = [
    0x0001,  # FL
    0x0002,  # FR
    0x0004,  # FC
    0x0008,  # LFE
    0x0010,  # BL
    0x0020,  # BR
    0x0040,  # FLC
    0x0080,  # FRC
    0x0100,  # BC
    0x0200,  # SL
    0x0400,  # SR
    0x0800,  # TC
    0x1000,  # TFL
    0x2000,  # TFC
    0x4000,  # TFR
    0x8000,  # TBL
    0x10000,  # TBC
    0x20000,  # TBR
]

META_CHUNKS = (b"bext", b"iXML", b"LIST", b"ds64")
TRACK_RE = re.compile(
    r"^(?P<base>.+?)_(?P<label>Tr\d+(?:-\d+)?|LR|XY|MS|Mix)$", re.IGNORECASE
)


def subformat_guid(format_tag: int) -> bytes:
    """WAVE_FORMAT_EXTENSIBLE 用 SubFormat GUID (PCM=1 / IEEE float=3)."""
    return struct.pack("<IHH", format_tag, 0x0000, 0x0010) + bytes(
        [0x80, 0x00, 0x00, 0xAA, 0x00, 0x38, 0x9B, 0x71]
    )


def channel_mask(n: int) -> int:
    mask = 0
    for bit in SPEAKER_POSITIONS[:n]:
        mask |= bit
    return mask


# ----------------------------------------------------------------------------
# WAV ヘッダ解析 (fmt / data 位置 / メタ chunk のみ読む軽量パーサ)
# ----------------------------------------------------------------------------
@dataclass
class WavInfo:
    path: Path
    label: str = ""                 # Tr1 / Tr2 / LR など
    format_tag: int = 1             # 有効フォーマット (1=PCM, 3=float)
    raw_format: int = 1
    channels: int = 1
    sample_rate: int = 48000
    bits: int = 32
    valid_bits: int = 0
    block_align: int = 4
    data_offset: int = 0
    data_size: int = 0
    chunks: dict = field(default_factory=dict)  # b'bext' -> bytes 等

    @property
    def bytes_per_sample(self) -> int:
        return (self.bits + 7) // 8

    @property
    def frames(self) -> int:
        return self.data_size // self.block_align if self.block_align else 0


def parse_wav(path: Path) -> WavInfo:
    info = WavInfo(path=path)
    with open(path, "rb") as f:
        head = f.read(12)
        if len(head) < 12 or head[8:12] != b"WAVE":
            raise ValueError(f"WAVファイルではありません: {path}")
        if head[0:4] not in (b"RIFF", b"RF64", b"BW64"):
            raise ValueError(f"RIFF/RF64ではありません: {path}")
        ds64_data_size = None
        while True:
            hdr = f.read(8)
            if len(hdr) < 8:
                break
            cid, size = hdr[0:4], struct.unpack("<I", hdr[4:8])[0]
            here = f.tell()
            if cid == b"fmt ":
                raw = f.read(min(size, 64))
                (info.raw_format, info.channels, info.sample_rate,
                 _byte_rate, info.block_align, info.bits) = struct.unpack("<HHIIHH", raw[:16])
                info.format_tag = info.raw_format
                if info.raw_format == 0xFFFE and size >= 40:
                    info.valid_bits = struct.unpack("<H", raw[18:20])[0]
                    info.format_tag = struct.unpack("<I", raw[24:28])[0]
            elif cid == b"data":
                real_size = size
                if size == 0xFFFFFFFF and ds64_data_size is not None:
                    real_size = ds64_data_size
                info.data_offset, info.data_size = here, real_size
                f.seek(real_size + (real_size & 1), 1)
                continue
            elif cid in META_CHUNKS and size <= 32 * 1024 * 1024:
                data = f.read(size)
                info.chunks[cid] = data
                if cid == b"ds64" and len(data) >= 16:
                    ds64_data_size = struct.unpack("<Q", data[8:16])[0]
            else:
                f.seek(size, 1)
            if size & 1:
                f.seek(1, 1)
    if info.format_tag not in (1, 3):
        raise ValueError(f"未対応フォーマット(tag={info.format_tag}): {path.name}")
    if info.bits % 8 != 0:
        raise ValueError(f"未対応ビット深度({info.bits}bit): {path.name}")
    return info


# ----------------------------------------------------------------------------
# iXML: トラック名の取得と TRACK_LIST 再構築
# ----------------------------------------------------------------------------
def ixml_track_names(info: WavInfo) -> list:
    """入力 iXML の TRACK_LIST からチャンネル順のトラック名を返す (無ければ空)."""
    raw = info.chunks.get(b"iXML")
    if not raw:
        return []
    try:
        root = ET.fromstring(raw.decode("utf-8", errors="replace").strip("\x00"))
    except ET.ParseError:
        return []
    tracks = []
    for tl in root.iter("TRACK_LIST"):
        for tr in tl.findall("TRACK"):
            idx_el = tr.find("CHANNEL_INDEX")
            name_el = tr.find("NAME")
            idx = int(idx_el.text) if idx_el is not None and idx_el.text else len(tracks) + 1
            tracks.append((idx, (name_el.text or "").strip() if name_el is not None else ""))
        break
    tracks.sort(key=lambda t: t[0])
    return [name for _idx, name in tracks]


def default_channel_names(info: WavInfo, names_from_ixml: list) -> list:
    """ステレオファイルは必ず L / R の独立チャンネルとして名前を付ける。

    例: *_LR.WAV → [LR-L, LR-R] / *_Tr1-2.WAV (iXML名が Tr1/Tr2) → [Tr1, Tr2]
    Poly WAV 内ではステレオペアも全てモノラルchの並びになるので、
    DAW側では L と R が別トラックとして扱われる。
    """
    names = [n for n in names_from_ixml if n]
    if info.channels == 1:
        return [names[0] if names else info.label]
    sides = ["L", "R"] + [str(i + 1) for i in range(2, info.channels)]
    if len(names) == info.channels:
        # 名前が 'L'/'R' 単体やラベルそのもの等で判別しにくい場合は ラベル-L / ラベル-R に正規化
        if all(n.upper() in ("L", "R", info.label.upper()) for n in names):
            return [f"{info.label}-{s}" for s in sides[:info.channels]]
        return names
    base = names[0] if names else info.label
    return [f"{base}-{s}" for s in sides[:info.channels]]


def channel_map_text(chan_names: list) -> str:
    """'1=Tr1, 2=Tr2, 3=LR-L, 4=LR-R' 形式のチャンネル割当表。"""
    return ", ".join(f"{i + 1}={n}" for i, n in enumerate(chan_names))


def patch_bext(bext: bytes | None, chan_names: list) -> bytes | None:
    """bext の Description (先頭256byte) 末尾にチャンネル割当を追記する (サイズ不変)。"""
    if not bext or len(bext) < 256:
        return bext
    desc = bext[:256].split(b"\x00")[0]
    add = f" | PolyCH: {channel_map_text(chan_names)}".encode("utf-8", errors="replace")
    if len(desc) + len(add) > 256:
        desc = desc[:max(0, 256 - len(add))]
    return (desc + add).ljust(256, b"\x00") + bext[256:]


def build_list_info(chan_names: list) -> bytes:
    """LIST/INFO chunk 本体: ICMT にチャンネル割当を入れる (メタデータビューア等で読める)。"""
    text = f"PolyWAV channels: {channel_map_text(chan_names)}".encode("utf-8") + b"\x00"
    sub = b"ICMT" + struct.pack("<I", len(text)) + text + (b"\x00" if len(text) & 1 else b"")
    return b"INFO" + sub


def build_ixml(infos: list, chan_names: list) -> bytes | None:
    """先頭ファイルの iXML を土台に TRACK_LIST を再構築。無ければ新規生成。"""
    base_raw = None
    for inf in infos:
        if inf.chunks.get(b"iXML"):
            base_raw = inf.chunks[b"iXML"]
            break
    root = None
    template_track = None
    if base_raw:
        try:
            root = ET.fromstring(base_raw.decode("utf-8", errors="replace").strip("\x00"))
            for tl in root.iter("TRACK_LIST"):
                old = tl.findall("TRACK")
                if old:
                    template_track = copy.deepcopy(old[0])
                break
        except ET.ParseError:
            return base_raw  # パース不能なら原文をそのまま継承
    if root is None:
        root = ET.Element("BWFXML")
        ET.SubElement(root, "IXML_VERSION").text = "1.61"
    track_list = None
    for tl in root.iter("TRACK_LIST"):
        track_list = tl
        break
    if track_list is None:
        track_list = ET.SubElement(root, "TRACK_LIST")
    # 既存 TRACK を全て消して作り直す
    for tr in list(track_list.findall("TRACK")):
        track_list.remove(tr)
    count_el = track_list.find("COUNT")
    if count_el is None:
        count_el = ET.Element("COUNT")
        track_list.insert(0, count_el)
    count_el.text = str(len(chan_names))
    for i, name in enumerate(chan_names, start=1):
        tr = copy.deepcopy(template_track) if template_track is not None else ET.Element("TRACK")
        def set_child(tag, value):
            el = tr.find(tag)
            if el is None:
                el = ET.SubElement(tr, tag)
            el.text = str(value)
        set_child("CHANNEL_INDEX", i)
        set_child("INTERLEAVE_INDEX", i)
        set_child("NAME", name)
        track_list.append(tr)
    return b'<?xml version="1.0" encoding="UTF-8"?>\r\n' + ET.tostring(root, encoding="utf-8")


# ----------------------------------------------------------------------------
# テイク検出と並び順
# ----------------------------------------------------------------------------
def track_sort_key(label: str, lr_first: bool, order: list | None):
    lab = label.upper()
    if order:
        for i, o in enumerate(order):
            if lab.startswith(o.upper()):
                return (i, 0)
        return (len(order), 0)
    if lab == "MIX":
        return (90, 0)
    if lab in ("LR", "XY", "MS"):
        return ((0, 0) if lr_first else (50, 0))
    m = re.match(r"TR(\d+)", lab)
    if m:
        return (10, int(m.group(1)))
    return (60, 0)


def collect_take(folder: Path, include_mix: bool, lr_first: bool, order: list | None):
    """1フォルダ内のWAVをテイク(ベース名)ごとにグループ化して返す。"""
    wavs = sorted([p for p in folder.iterdir()
                   if p.is_file() and p.suffix.lower() == ".wav"])
    groups: dict[str, list] = {}
    loose: list = []
    for p in wavs:
        m = TRACK_RE.match(p.stem)
        if m:
            label = m.group("label")
            # 正規化: Tr の T のみ大文字 (Tr1), LR等は大文字
            label = ("Tr" + label[2:]) if label.lower().startswith("tr") else label.upper()
            if label.upper() == "MIX" and not include_mix:
                continue
            groups.setdefault(m.group("base").lower(), []).append((p, label, m.group("base")))
        else:
            loose.append(p)
    takes = []
    for _key, items in sorted(groups.items()):
        items.sort(key=lambda t: track_sort_key(t[1], lr_first, order))
        takes.append((items[0][2], folder, [(p, lab) for p, lab, _b in items]))
    if loose and not groups:
        items = [(p, p.stem) for p in loose]
        takes.append((folder.name, folder, items))
    return takes


def find_takes(root: Path, include_mix: bool, lr_first: bool, order: list | None):
    """ファイル/フォルダを受け取り (base, folder, [(path,label)...]) の一覧を返す。"""
    if root.is_file():
        return [(root.stem, root.parent, [(root, root.stem)])]
    takes = []
    for dirpath, _dirs, _files in os_walk_sorted(root):
        takes.extend(collect_take(dirpath, include_mix, lr_first, order))
    return takes


def os_walk_sorted(root: Path):
    for dirpath, dirs, files in __import__("os").walk(root):
        dirs.sort()
        yield Path(dirpath), dirs, files


# ----------------------------------------------------------------------------
# 変換本体
# ----------------------------------------------------------------------------
def convert_take(base: str, files: list, out_path: Path, dry_run: bool = False) -> dict:
    infos = []
    for path, label in files:
        inf = parse_wav(path)
        inf.label = label
        infos.append(inf)

    ref = infos[0]
    for inf in infos[1:]:
        if inf.sample_rate != ref.sample_rate:
            raise ValueError(f"サンプルレート不一致: {inf.path.name}={inf.sample_rate} / {ref.path.name}={ref.sample_rate}")
        if inf.bits != ref.bits or inf.format_tag != ref.format_tag:
            raise ValueError(f"フォーマット不一致: {inf.path.name} ({inf.format_tag}/{inf.bits}bit) vs {ref.path.name} ({ref.format_tag}/{ref.bits}bit)")

    total_ch = sum(i.channels for i in infos)
    frames_out = max(i.frames for i in infos)
    bps = ref.bytes_per_sample
    total_block = total_ch * bps
    padded = [i.path.name for i in infos if i.frames != frames_out]

    chan_names = []
    for inf in infos:
        chan_names.extend(default_channel_names(inf, ixml_track_names(inf)))

    result = {
        "base": base, "output": str(out_path), "channels": total_ch,
        "sample_rate": ref.sample_rate, "bits": ref.bits,
        "format": "float" if ref.format_tag == 3 else "PCM",
        "frames": frames_out, "tracks": [(i.path.name, i.label, i.channels) for i in infos],
        "channel_names": chan_names, "padded": padded,
    }
    if dry_run:
        return result

    bext = patch_bext(
        next((i.chunks[b"bext"] for i in infos if i.chunks.get(b"bext")), None), chan_names)
    ixml = build_ixml(infos, chan_names)
    list_info = build_list_info(chan_names)
    result["channel_map"] = channel_map_text(chan_names)

    data_bytes = frames_out * total_block
    use_ext = total_ch > 2 or ref.raw_format == 0xFFFE or ref.format_tag == 3
    fmt_body = struct.pack(
        "<HHIIHH", 0xFFFE if use_ext else ref.format_tag, total_ch, ref.sample_rate,
        ref.sample_rate * total_block, total_block, ref.bits)
    if use_ext:
        fmt_body += struct.pack("<HHI", 22, ref.valid_bits or ref.bits, channel_mask(total_ch)) \
            + subformat_guid(ref.format_tag)
    fact_body = struct.pack("<I", frames_out) if (ref.format_tag == 3 or use_ext) else None

    def chunk_size(body_len):
        return 8 + body_len + (body_len & 1)

    riff_payload = 4 + chunk_size(len(fmt_body))
    if fact_body:
        riff_payload += chunk_size(len(fact_body))
    if bext:
        riff_payload += chunk_size(len(bext))
    riff_payload += chunk_size(len(list_info))
    if ixml:
        riff_payload += chunk_size(len(ixml))
    riff_payload += 8 + data_bytes + (data_bytes & 1)
    use_rf64 = riff_payload + 8 >= 0xFFFFF000

    handles = [open(i.path, "rb") for i in infos]
    try:
        for h, inf in zip(handles, infos):
            h.seek(inf.data_offset)
        with open(out_path, "wb") as out:
            ds64_pos = None
            if use_rf64:
                out.write(b"RF64" + struct.pack("<I", 0xFFFFFFFF) + b"WAVE")
                ds64_pos = out.tell()
                out.write(b"ds64" + struct.pack("<I", 28) + b"\x00" * 28)
                riff_payload += 36
            else:
                out.write(b"RIFF" + struct.pack("<I", riff_payload) + b"WAVE")

            def write_chunk(cid: bytes, body: bytes):
                out.write(cid + struct.pack("<I", len(body)) + body)
                if len(body) & 1:
                    out.write(b"\x00")

            write_chunk(b"fmt ", fmt_body)
            if fact_body:
                write_chunk(b"fact", fact_body)
            if bext:
                write_chunk(b"bext", bext)
            write_chunk(b"LIST", list_info)
            if ixml:
                write_chunk(b"iXML", ixml)
            out.write(b"data" + struct.pack("<I", 0xFFFFFFFF if use_rf64 else data_bytes))

            block_frames = 16384 if np is not None else 2048
            remaining = frames_out
            while remaining > 0:
                n = min(block_frames, remaining)
                if np is not None:
                    block = np.zeros((n, total_ch, bps), dtype=np.uint8)
                    dest = 0
                    for h, inf in zip(handles, infos):
                        raw = h.read(n * inf.block_align)
                        got = len(raw) // inf.block_align
                        if got:
                            arr = np.frombuffer(raw[:got * inf.block_align], dtype=np.uint8) \
                                    .reshape(got, inf.channels, bps)
                            block[:got, dest:dest + inf.channels, :] = arr
                        dest += inf.channels
                    out.write(block.tobytes())
                else:
                    raws = []
                    for h, inf in zip(handles, infos):
                        raw = h.read(n * inf.block_align)
                        raws.append((raw, inf))
                    block = bytearray(n * total_block)
                    for fi in range(n):
                        o = fi * total_block
                        for raw, inf in raws:
                            s = fi * inf.block_align
                            seg = raw[s:s + inf.block_align]
                            block[o:o + len(seg)] = seg
                            o += inf.block_align
                    out.write(bytes(block))
                remaining -= n
            if data_bytes & 1:
                out.write(b"\x00")
            if use_rf64 and ds64_pos is not None:
                out.seek(ds64_pos + 8)
                out.write(struct.pack("<QQQI", riff_payload, data_bytes, frames_out, 0))
    finally:
        for h in handles:
            h.close()
    return result


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="パラWAV → Poly WAV 結合変換 (標準ライブラリのみ / スマホ・Mac対応)")
    ap.add_argument("inputs", nargs="*", help="テイクフォルダ / 親フォルダ / WAV (複数可・D&D可)")
    ap.add_argument("--outdir", type=Path, default=None)
    ap.add_argument("--include-mix", action="store_true", help="*_Mix.WAV も含める")
    ap.add_argument("--lr-first", action="store_true", help="LR/XY を先頭に置く")
    ap.add_argument("--order", default=None, help="チャンネル順をカンマ区切りで指定 (例: LR,Tr1,Tr2)")
    ap.add_argument("--inplace", action="store_true", help="テイクフォルダ内に出力")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--suffix", default="_POLY")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    inputs = list(args.inputs)
    if not inputs:
        raw = input("テイクフォルダ (または親フォルダ) のパスを貼り付けて Enter: ").strip().strip("'\"")
        if not raw:
            print("入力がありません。")
            return 1
        inputs = [raw]
    order = [s.strip() for s in args.order.split(",")] if args.order else None

    rc = 0
    reserved: set = set()  # この実行で作る出力先。複数フォルダ投入時の同名衝突回避用
    for raw in inputs:
        root = Path(raw.strip().strip("'\"")).expanduser()
        if not root.exists():
            print(f"✗ 見つかりません: {root}")
            rc = 1
            continue
        takes = find_takes(root, args.include_mix, args.lr_first, order)
        if not takes:
            print(f"✗ WAVが見つかりません: {root}")
            rc = 1
            continue
        for base, folder, files in takes:
            if args.outdir:
                out_dir = args.outdir
            elif args.inplace or folder == root and root.is_file():
                out_dir = folder
            elif folder == root:
                out_dir = folder.parent
            else:
                out_dir = root
            out_dir.mkdir(parents=True, exist_ok=True)
            # フォルダごとに必ず1ファイルずつ出す: この実行内で同名になった場合は
            # テイクフォルダ名を前置して別ファイル化する (絶対に合体させない)
            out_path = out_dir / f"{base}{args.suffix}.wav"
            if str(out_path) in reserved:
                stem = f"{folder.name}_{base}" if folder.name != base else base
                candidate = out_dir / f"{stem}{args.suffix}.wav"
                n = 2
                while str(candidate) in reserved or (candidate.exists() and not args.overwrite):
                    candidate = out_dir / f"{stem}{args.suffix}_{n}.wav"
                    n += 1
                out_path = candidate
            if out_path.exists() and not args.overwrite and not args.dry_run:
                print(f"⏭  既にあります (スキップ): {out_path}  ※上書きは --overwrite")
                continue
            reserved.add(str(out_path))
            try:
                r = convert_take(base, files, out_path, dry_run=args.dry_run)
            except Exception as e:
                print(f"✗ {base}: {e}")
                rc = 1
                continue
            print(f"{'🔍' if args.dry_run else '✅'} {base}: "
                  f"{r['channels']}ch / {r['sample_rate']}Hz / {r['bits']}bit {r['format']} / "
                  f"{r['frames']} frames")
            for name, label, ch in r["tracks"]:
                print(f"    - {label} ({ch}ch) ← {name}")
            print(f"    ch名: {', '.join(r['channel_names'])}")
            if r["padded"]:
                print(f"    ⚠ 長さが違うトラックを無音でパディング: {', '.join(r['padded'])}")
            if not args.dry_run:
                print(f"    → {r['output']}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
