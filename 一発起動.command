#!/bin/zsh
# パラWAV → Poly WAV 一発起動 (Mac)
# 使い方: テイクフォルダ/親フォルダをこのファイルにドラッグ&ドロップ
#         引数なしでダブルクリックした場合はフォルダ選択ダイアログが出ます
cd "$(dirname "$0")"
if [ $# -eq 0 ]; then
  FOLDER=$(osascript -e 'POSIX path of (choose folder with prompt "テイクフォルダ（または親フォルダ）を選んでください")' 2>/dev/null)
  if [ -z "$FOLDER" ]; then echo "キャンセルしました"; exit 0; fi
  python3 poly_wav.py "$FOLDER"
else
  python3 poly_wav.py "$@"
fi
echo ""
echo "終わりました。このウィンドウは閉じてOKです。"
read -k 1 -s "?何かキーを押すと閉じます…"
