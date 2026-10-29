# Poly WAV メーカー（パラWAV → Polyphonic WAV）

ZOOM H6essential（H6e）等のフィールドレコーダーがトラックごとに分離保存したWAV（パラWAV）を、1つのマルチチャンネル Poly WAV（BWF）に束ねるツールです。ブラウザ版はインストール不要で、誰でもURLを開くだけで使えます。

**公開URL（ブラウザ版）: https://thunder923.github.io/poly-wav-maker/**

```
ZOOM0001/
  ZOOM0001_Tr1.WAV ┐
  ZOOM0001_Tr2.WAV ├─→  ZOOM0001_POLY.wav （4ch / 元フォーマットのまま）
  ZOOM0001_LR.WAV  ┘     ※ ZOOM0001_Mix.WAV（2MIX）は既定で除外
```

## できること

- テイクフォルダ（またはSDカード全体）を渡すだけで、フォルダごとに1本の Poly WAV を出力
- 波形を再変換しないので **32-bit float / 24-bit / 16-bit / 32-bit int をビットパーフェクト維持**
- ステレオトラックは L / R を別々のモノラルchに分割して収録（DAWで独立トラックとして扱える）
- チャンネル割当を **bext / iXML / LIST-INFO の3層メタデータ** に埋め込み
- 出力4GB超は **RF64** で自動書き出し
- Python版（標準ライブラリのみ）とブラウザ版の2系統。用途に合わせて選べます

## 同梱ファイル

| ファイル | 用途 |
|---|---|
| `poly_wav.py` | Python版本体。**Python標準ライブラリのみ**（numpyがあれば自動で高速化）。Mac / Windows / iPhone / Android 共通 |
| `poly_wav.html` / `index.html` | **ブラウザ版**。インストール不要、Safari/Chrome/Edgeで開くだけ。オフライン可・ファイルは外部送信されない |
| `一発起動.command` | Mac用ランチャー（ダブルクリックでフォルダ選択、またはフォルダをドラッグ＆ドロップ） |
| `一発起動_Windows.bat` | Windows用ランチャー（複数フォルダのドラッグ＆ドロップ可、ダブルクリックでフォルダ選択ダイアログ） |

## 使い方

### ブラウザ版（いちばん簡単・公開URL）
1. https://thunder923.github.io/poly-wav-maker/ を開く
2. テイクフォルダを選ぶ（またはWAVファイルをまとめて選択）
3. 「変換」→ 出来た `*_POLY.wav` を保存

手元の `poly_wav.html` をブラウザで開いても同じように使えます。

### Mac（.command）
1. `一発起動.command` をダブルクリック → フォルダ選択でテイクフォルダ（またはSDカード全体）を選ぶ
2. または、フォルダを `一発起動.command` にドラッグ＆ドロップ

※ 初回だけ「開発元を確認できないため開けない」が出たら、右クリック→「開く」で許可。

### Windows（.bat）
1. 事前に Python 3 を入れる（python.org のインストーラで「Add python.exe to PATH」にチェック）
2. テイクフォルダ（複数選択可）を `一発起動_Windows.bat` にドラッグ＆ドロップ
3. ダブルクリックだけの場合はフォルダ選択ダイアログが出る

### コマンドライン
```bat
py -3 poly_wav.py D:\ZOOM0001 D:\ZOOM0002
```
```bash
python3 poly_wav.py /Volumes/SDCARD/ZOOM0001        # テイク1つ
python3 poly_wav.py /Volumes/SDCARD                 # 配下の全テイクを一括
python3 poly_wav.py ZOOM0001 --include-mix          # 2MIXも含める
python3 poly_wav.py ZOOM0001 --lr-first --dry-run   # 変換せず割当確認だけ
```

### iPhone / iPad（ブラウザ版・推奨）
1. `poly_wav.html` を「ファイル」アプリに保存
2. ファイルアプリでタップ（Safariで開く）→「ファイルを選ぶ」で対象WAVを複数選択
   ※ フォルダ丸ごと選択はiOS Safari非対応のため、テイク内のWAVを全選択してください
3. 「変換」→ 出来た `*_POLY.wav` の保存ボタンをタップして「ファイルに保存」

※ 巨大なテイク（数GB）はメモリ不足になることがあります。その場合はPython版かMacで。

### iPhone / iPad（Python版: a-Shell）
1. App Storeで **a-Shell**（無料）を入れる
2. a-Shellで `poly_wav.py` とテイクフォルダのある場所を開く
   （`pickFolder` コマンドでSDカード/ファイルアプリのフォルダへアクセス可）
3. `python3 poly_wav.py ZOOM0001` — 標準ライブラリのみなので追加インストール不要

### Android
- ブラウザ版: `poly_wav.html` をChromeで開く（フォルダ選択も可）
- Python版: **Pydroid 3** または Termux で `python3 poly_wav.py <フォルダ>`

## 精度・仕様

- 波形はデコードせず、data chunkをサンプル単位のバイト列としてそのままインターリーブ
  → **32-bit float / 24-bit / 16-bit / 32-bit int をビットパーフェクト維持**（再量子化・クリッピングなし）
- サンプルレート不一致・フォーマット不一致のテイクはエラーにして止める（黙って変換しない）
- **複数フォルダを投げても合体しない**: フォルダ（テイク）ごとに必ず1ファイルずつ出力する。
  出力先で同名が重なった場合はフォルダ名を前置する／連番を付けて別ファイルにする（上書き・混合しない）
- **ステレオは L / R を別々のモノラルchに分けて収録**する: 例 `ZOOM0001_LR.WAV` → ch3=`LR-L`、ch4=`LR-R`。
  Poly WAV内は全chモノラルなので、DAWでは L と R が独立トラックとして扱える
- チャンネル順: 既定は `Tr1, Tr2, … , LR`。`--lr-first` でLR先頭、`--order LR,Tr1,Tr2` で任意指定
- 長さが違うトラックは最長に合わせて無音パディングし、対象ファイル名を表示する
- **チャンネル割当メタデータ（3層で埋め込み）**:
  - **iXML** TRACK_LIST: 全ch分の `CHANNEL_INDEX / NAME`（例: 1=Tr1, 2=Tr2, 3=LR-L, 4=LR-R）
  - **bext** Description末尾に `PolyCH: 1=Tr1, 2=Tr2, 3=LR-L, 4=LR-R` を追記（元の説明文・TimeReference等は保持）
  - **LIST/INFO (ICMT)** にも同じ割当表を記録（メタデータビューアや一部DAWで読める）
- **bext**: 先頭トラックのchunkを継承（TimeReference等）
- **iXML**: TRACK_LISTを出力ch数で再構築し、各ch名（入力iXMLのNAME優先、ステレオは-L/-Rに分割）を継承
- 多ch / float は WAVE_FORMAT_EXTENSIBLE（チャンネルマスク付き）、出力4GB超は RF64 で書き出し
- 出力先: テイクフォルダ指定時はその**親フォルダ**、親フォルダ指定時はその中。`--outdir` / `--inplace` で変更可
- 既存出力はスキップ（上書きは `--overwrite`）

## データの扱い

- 入力ファイルは変更しません（読み取りのみ）
- ブラウザ版はすべての処理を端末内で行い、ファイルが外部に送信されることはありません

## 動作確認（開発時テスト）
H6e想定の合成WAV（32f/48kHz: Tr1+Tr2+LR=4ch、24bit/96kHz: 2ch、bext/iXML付き）で検証済み:
- 出力を逆分離した各chが入力と**バイト完全一致**
- bext継承・iXMLのTRACK_LIST再構築（4トラック分のNAME）を確認
- Mix除外 / `--include-mix` / `--lr-first` の並び替えを確認

## 注意
- Pro Toolsへは Poly WAV をそのままドラッグで取り込めます（マルチチャンネル・インターリーブ形式）。
  分離したい場合は Pro Tools 側で「Split to Mono」してください。
