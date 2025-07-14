import os
import fnmatch
from datetime import datetime, timezone
from typing import Dict

async def find_matching_files(source_folder: str, pattern: str = "*") -> Dict[str, Dict]:
    """Walk `source_folder` and return {rel_path: {'mtime':…, 'size':…}}."""
    files: Dict[str, Dict] = {}
    if not os.path.exists(source_folder):
        return files
    for root, _, filenames in os.walk(source_folder):
        for name in filenames:
            if fnmatch.fnmatch(name, pattern):
                full_path = os.path.join(root, name)
                relative = os.path.relpath(full_path, source_folder)
                try:
                    stat = os.stat(full_path)
                    files[relative] = {
                        'mtime': datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                        'size': stat.st_size
                    }
                except OSError:
                    continue
    return files 
