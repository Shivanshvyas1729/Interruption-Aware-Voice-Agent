"""
strip_emojis.py — Fix encoding corruption AND remove all emojis from index.html.

The PowerShell script previously mangled UTF-8 emojis by reading them as cp1252.
This script:
  1. Recovers the file to correct UTF-8 by reversing the cp1252 double-encoding.
  2. Strips all emoji/special Unicode symbols, replacing with plain text equivalents
     or removing them entirely.
"""
import re, sys

FILE = r"c:\Users\DELL\Desktop\pivot\client\phase1_minimal_harness\index.html"

# ── Step 1: reverse the cp1252 double-encoding ───────────────────────────────
with open(FILE, "rb") as f:
    raw = f.read()

text = raw.decode("utf-8", errors="replace")

try:
    # Re-encode as cp1252 to recover the original UTF-8 byte stream
    text = text.encode("cp1252", errors="ignore").decode("utf-8", errors="replace")
    print("Encoding recovery: OK")
except Exception as e:
    print(f"Encoding recovery skipped: {e}")

# ── Step 2: strip emojis and Unicode symbols ─────────────────────────────────
# Match emoji/symbol ranges but keep normal Latin extended (for quotes, dashes, etc.)
EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FFFF"   # Emoticons, transport, misc symbols, etc.
    "\U00002600-\U000027BF"   # Misc symbols & dingbats
    "\U00002700-\U000027BF"   # Dingbats
    "\U0000FE00-\U0000FE0F"   # Variation selectors
    "\U0000200D"              # Zero-width joiner
    "\U00002194-\U00002199"   # Arrows
    "\U000025A0-\U000025FF"   # Geometric shapes
    "\U00002300-\U000023FF"   # Misc technical (⏱ etc.)
    "]+",
    flags=re.UNICODE,
)

text_clean = EMOJI_RE.sub("", text)

# Fix common HTML text artifacts: replace remaining mangled sequences with clean ASCII
MANUAL = [
    # em dash / en dash
    ("\u00e2\u0080\u0094", "—"),
    ("\u00e2\u0080\u0093", "–"),
    # curly quotes
    ("\u00e2\u0080\u009d", '"'),
    ("\u00e2\u0080\u009c", '"'),
    ("\u00e2\u0080\u0099", "'"),
    ("\u00e2\u0080\u0098", "'"),
    # bullet
    ("\u00e2\u0080\u00a2", "•"),
    # arrow →
    ("\u00e2\u0086\u0092", "→"),
    # replacement char
    ("\ufffd", ""),
]
for bad, good in MANUAL:
    text_clean = text_clean.replace(bad, good)

# ── Step 3: save ─────────────────────────────────────────────────────────────
with open(FILE, "w", encoding="utf-8") as f:
    f.write(text_clean)

n_emojis = len(EMOJI_RE.findall(text))
print(f"Emojis removed: {n_emojis} groups")
print(f"File saved: {FILE}")
print("Done.")
