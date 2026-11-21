"""Inline the editable JS into the portable HTML; keep the original UI intact."""
from pathlib import Path

root = Path(__file__).parent / 'static'
page = (root / 'index.html').read_text(encoding='utf-8')
script = (root / 'app.js').read_text(encoding='utf-8')
prefix = page.split('<script>')[0]
suffix = page.split('</script>')[-1]
(root / 'index.html').write_text(prefix + '<script>' + script + '</script>' + suffix, encoding='utf-8')
