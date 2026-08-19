#!/usr/bin/env bash
# Render the poster to PNG (review) and PDF (deliverable) with headless Chrome.
#   ./render.sh            -> both
#   ./render.sh png        -> PNG only, fast loop while iterating
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
SCRATCH="C:/Users/jhoarau/AppData/Local/Temp/claude/C--PRIVEE-AZURE/20ceec7a-c519-4929-b1e5-cf708c593a88/scratchpad"
CHROME="/c/Program Files/Google/Chrome/Application/chrome.exe"
URL="file:///C:/PRIVEE/AZURE/docs/BST_DISCO_JH_2026/Poster/web/HOARAU_Poster_MScCSTE.html"
PY="C:/PRIVEE/GIT/SMART_GREEN_SUPPLY_CHAIN/VOLUME_ENTREPOT/.venv/Scripts/python.exe"

"$CHROME" --headless=new --disable-gpu --hide-scrollbars --virtual-time-budget=8000 \
  --window-size=2245,3179 --screenshot="$SCRATCH/poster.png" "$URL" >/dev/null 2>&1

"$PY" -c "
from PIL import Image
S='$SCRATCH/'
im=Image.open(S+'poster.png').convert('RGB')
im.resize((1000, round(im.height*1000/im.width)), Image.LANCZOS).save(S+'poster_view.png')
h=im.height//2
im.crop((0,0,im.width,h)).resize((1350,round(h*1350/im.width)),Image.LANCZOS).save(S+'poster_top.png')
im.crop((0,h,im.width,im.height)).resize((1350,round((im.height-h)*1350/im.width)),Image.LANCZOS).save(S+'poster_bot.png')
"

if [ "$1" != "png" ]; then
  "$CHROME" --headless=new --disable-gpu --no-pdf-header-footer \
    --print-to-pdf="$HERE/HOARAU_484338_Poster_MScCSTE.pdf" --virtual-time-budget=8000 \
    "$URL" >/dev/null 2>&1
  echo "pdf: $HERE/HOARAU_484338_Poster_MScCSTE.pdf"
fi
echo "png: $SCRATCH/poster.png"
