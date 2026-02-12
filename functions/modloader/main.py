import atexit
import signal
import subprocess
import sys
import tempfile

# Needed for embedded python
import os

import logging

# DO NOT IMPORT ANY FILES BEFORE THESE TWO LINES
file_dir = os.path.dirname(__file__)
sys.path.append(file_dir)

from modfolder import get_mod_folder
import patch
import sound

mod_zips_root_path = get_mod_folder()
os.makedirs(mod_zips_root_path, exist_ok=True)


# from functions.base.settings_manager import get_settings_manager
# game_path = get_settings_manager().get_setting("game_path")
game_path = '1123'

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(mod_zips_root_path, "log.txt")),
        logging.StreamHandler(stream=sys.stdout)
    ]
)

logging.info("Limbus Mod Loader version: v1.8")


def kill_handler(*args) -> None:
    sys.exit(0)


def cleanup_assets():
    try:
        logging.info("Cleaning up assets")
        patch.cleanup_assets()
        sound.restore_sound()
    except Exception as e:
        logging.error("Error: %s", e)

def main():
    try:
        logging.info("Limbus args: %s", sys.argv)
        cleanup_assets()
        atexit.register(cleanup_assets)

        logging.info("Detecting lunartique mods")
        patch.detect_lunartique_mods(mod_zips_root_path)
        tmp_asset_root = tempfile.mkdtemp()
        logging.info("Extracting mod assets to %s", tmp_asset_root)
        patch.extract_assets(tmp_asset_root, mod_zips_root_path)
        logging.info("Backing up data and patching assets....")
        patch.patch_assets(tmp_asset_root)
        patch.shutil.rmtree(tmp_asset_root)
        sound.replace_sound(mod_zips_root_path)
        logging.info("Starting game")

        # subprocess.call(sys.argv[1:])
        subprocess.Popen(['start', 'steam://rungameid/1973530'], shell=True)

    except Exception as e:
        logging.error("Error: %s", e)
        sys.exit(1)