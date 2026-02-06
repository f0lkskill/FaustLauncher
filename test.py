from webFunc import Note
from json import loads

n = Note("FaustLauncher", 'AutoTranslate')
n.fetch_note_info()
note = loads(n.note_content)
path = note['"llc_download_url"']['seven']
version = note['llc_version']

print(path, version)