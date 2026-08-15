#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fmodbank — command-line wrapper for FMOD Bank Tools
====================================================

Faithful port of the core logic of Wouldubeinta's Fmod-Bank-Tools
(https://github.com/Wouldubeinta/Fmod-Bank-Tools) to a pure CLI.

It reuses the original FMOD / FSBANK DLLs (fmod64.dll, fsbank64.dll,
libfsbvorbis64.dll) via ctypes, so no C++ compiler is needed.

Two operations (matching the original GUI tool):

  * extract  — parse a .bank (RIFF/FEV container), pull the embedded FSB
               files out, decode every subsound with FMOD into 16-bit PCM
               .wav files, and write a <bank>[i].txt list per FSB.
  * rebuild  — re-encode the (edited) wav files back into FSB with FSBANK,
               then stitch the new FSB data into the original .bank layout
               (updating the SNDH offsets and RIFF size) and write the
               rebuilt .bank out.

Usage examples:
  python fmodbank.py extract ./bank/Weapon.bank
  python fmodbank.py extract ./bank/Weapon.bank -o ./wav
  python fmodbank.py extract ./bank/
  python fmodbank.py rebuild  ./bank/Weapon.bank -w ./wav
  python fmodbank.py rebuild  ./bank/Weapon.bank -w ./wav --format pcm --quality 60
  python fmodbank.py info     ./bank/Weapon.bank
"""

import argparse
import ctypes
import os
import struct
import sys

CHUNK_SIZE = 262144  # 256 KiB read buffer, same as the original fileio.cpp


def default_cpu_threads():
    """默认编码线程数 = 一半 CPU 核心（FSBANK 并行编码用）。"""
    n = os.cpu_count() or 2
    return max(1, n // 2)

# ---------------------------------------------------------------------------
# Error string tables (ported from include/fmod_errors.h + fsbank_errors.h)
# ---------------------------------------------------------------------------

FMOD_ERRORS = {
    0x0: "No errors.",
    0x1: "Tried to call a function on a data type that does not allow this type of functionality.",
    0x2: "Error trying to allocate a channel.",
    0x3: "The specified channel has been reused to play another sound.",
    0x4: "DMA Failure.  See debug output for more information.",
    0x5: "DSP connection error.",
    0x6: "DSP return code from a DSP process query callback.",
    0x7: "DSP Format error.",
    0x8: "DSP is already in the mixer's DSP network.",
    0x9: "DSP connection error.  Couldn't find the DSP unit specified.",
    0xA: "DSP operation error.  Cannot perform operation on this DSP as it is reserved by the system.",
    0xB: "DSP return code from a DSP process query callback.",
    0xC: "DSP operation cannot be performed on a DSP of this type.",
    0xD: "Error loading file.",
    0xE: "Couldn't perform seek operation.",
    0xF: "Media was ejected while reading.",
    0x10: "End of file unexpectedly reached while trying to read essential data (truncated?).",
    0x11: "End of current chunk reached while trying to read data.",
    0x12: "File not found.",
    0x13: "Unsupported file, audio format or needs password for decryption.",
    0x14: "There is a version mismatch between the FMOD header and either the FMOD Studio library or the FMOD Low Level library.",
    0x15: "A HTTP error occurred.",
    0x16: "The specified resource requires authentication or is forbidden.",
    0x17: "Proxy authentication is required to access the specified resource.",
    0x18: "A HTTP server error occurred.",
    0x19: "The HTTP request timed out.",
    0x1A: "FMOD was not initialized correctly to support this function.",
    0x1B: "Cannot call this command after System::init.",
    0x1C: "An error occurred that wasn't supposed to.  Contact support.",
    0x1D: "Value passed in was a NaN, Inf or denormalized float.",
    0x1E: "An invalid object handle was used.",
    0x1F: "An invalid parameter was passed to this function.",
    0x20: "An invalid seek position was passed to this function.",
    0x21: "An invalid speaker was passed to this function based on the current speaker mode.",
    0x22: "The syncpoint did not come from this sound handle.",
    0x23: "Tried to call a function on a thread that is not supported.",
    0x24: "The vectors passed in are not unit length, or perpendicular.",
    0x25: "Reached maximum audible playback count for this sound's soundgroup.",
    0x26: "Not enough memory or resources.",
    0x27: "Can't use FMOD_OPENMEMORY_POINT on non PCM source data.",
    0x28: "Tried to call a command on a 2d sound when the command was meant for 3d sound.",
    0x29: "Tried to use a feature that requires hardware support.",
    0x2A: "Couldn't connect to the specified host.",
    0x2B: "A socket error occurred.",
    0x2C: "The specified URL couldn't be resolved.",
    0x2D: "Operation on a non-blocking socket could not complete immediately.",
    0x2E: "Operation could not be performed because specified sound/DSP connection is not ready.",
    0x2F: "Error initializing output device, but more specifically, the output device is already in use and cannot be reused.",
    0x30: "Error creating hardware sound buffer.",
    0x31: "A call to a standard soundcard driver failed.",
    0x32: "Soundcard does not support the specified format.",
    0x33: "Error initializing output device.",
    0x34: "The output device has no drivers installed.",
    0x35: "An unspecified error has been returned from a plugin.",
    0x36: "A requested output, dsp unit type or codec was not available.",
    0x37: "A resource that the plugin requires cannot be found.",
    0x38: "A plugin was built with an unsupported SDK version.",
    0x39: "An error occurred trying to initialize the recording device.",
    0x3A: "Reverb properties cannot be set on this channel.",
    0x3B: "Specified instance in FMOD_REVERB_PROPERTIES couldn't be set.",
    0x3C: "The error occurred because the sound referenced contains subsounds when it shouldn't have.",
    0x3D: "This subsound is already being used by another sound.",
    0x3E: "Shared subsounds cannot be replaced or moved from their parent stream.",
    0x3F: "The specified tag could not be found or there are no tags.",
    0x40: "The sound created exceeds the allowable input channel count.",
    0x41: "The retrieved string is too long to fit in the supplied buffer and has been truncated.",
    0x42: "Something in FMOD hasn't been implemented when it should be!",
    0x43: "This command failed because System::init or System::setDriver was not called.",
    0x44: "A command issued was not supported by this object.",
    0x45: "The version number of this file format is not supported.",
    0x46: "The specified bank has already been loaded.",
    0x47: "The live update connection failed due to the game already being connected.",
    0x48: "The live update connection failed due to the game data being out of sync with the tool.",
    0x49: "The live update connection timed out.",
    0x4A: "The requested event, bus or vca could not be found.",
    0x4B: "The Studio::System object is not yet initialized.",
    0x4C: "The specified resource is not loaded, so it can't be unloaded.",
    0x4D: "An invalid string was passed to this function.",
    0x4E: "The specified resource is already locked.",
    0x4F: "The specified resource is not locked, so it can't be unlocked.",
    0x50: "The specified recording driver has been disconnected.",
    0x51: "The length provided exceeds the allowable limit.",
}

FSBANK_ERRORS = {
    0: "No errors.",
    1: "An expected chunk is missing from the cache, perhaps try deleting cache files.",
    2: "The build process was cancelled during compilation by the user.",
    3: "The build process cannot continue due to previously ignored errors.",
    4: "Encoder for chosen format has encountered an unexpected error.",
    5: "Encoder initialization failed.",
    6: "Encoder for chosen format is not supported on this platform.",
    7: "An operating system based file error was encountered.",
    8: "A specified file could not be found.",
    9: "Internal error from FMOD sub-system.",
    10: "Already initialized.",
    11: "The format of the source file is invalid.",
    12: "An invalid parameter has been passed to this function.",
    13: "Ran out of memory.",
    14: "Not initialized yet.",
    15: "Chosen encode format is not supported by this FSB version.",
    16: "Source file is too short for seamless looping. Looping disabled.",
    17: "FSBANK_BUILD_FILTERHIGHFREQ flag ignored: feature only supported by XMA format.",
    18: "FSBANK_BUILD_DISABLESEEKING flag ignored: feature only supported by XMA format.",
    19: "FSBANK_BUILD_FSB5_DONTWRITENAMES flag forced: cannot write names when source is from memory.",
    20: "External encoder dynamic library not found",
    21: "External encoder dynamic library could not be loaded.",
}

# ---------------------------------------------------------------------------
# FMOD constants
# ---------------------------------------------------------------------------
FMOD_OK = 0
FMOD_OPENONLY = 0x00002000          # Just open the file, dont prebuffer or read.
FMOD_INIT_NORMAL = 0x00000000
FMOD_TIMEUNIT_PCMBYTES = 0x00000004

# FSBANK constants
FSBANK_FSBVERSION_FSB5 = 0
FSBANK_INIT_GENERATEPROGRESSITEMS = 0x00000010
FSBANK_FORMAT_PCM = 0
FSBANK_FORMAT_VORBIS = 5
FSBANK_FORMAT_FADPCM = 6
FSBANK_BUILD_DISABLESYNCPOINTS = 0x00000001
FSBANK_BUILD_DONTLOOP = 0x00000002
FSBANK_BUILD_FSB5_DONTWRITENAMES = 0x00000080
FSBANK_BUILD_WRITEPEAKVOLUME = 0x00000200
FSBANK_STATE_FINISHED = 5
FSBANK_STATE_FAILED = 6
FSBANK_STATE_WARNING = 7


# ---------------------------------------------------------------------------
# ctypes structure definitions (layouts taken from fmod_common.h / fsbank.h)
# ---------------------------------------------------------------------------

class FMOD_CREATESOUNDEXINFO(ctypes.Structure):
    _fields_ = [
        ("cbsize", ctypes.c_int),
        ("length", ctypes.c_uint),
        ("fileoffset", ctypes.c_uint),
        ("numchannels", ctypes.c_int),
        ("defaultfrequency", ctypes.c_int),
        ("format", ctypes.c_int),
        ("decodebuffersize", ctypes.c_uint),
        ("initialsubsound", ctypes.c_int),
        ("numsubsounds", ctypes.c_int),
        ("inclusionlist", ctypes.c_void_p),
        ("inclusionlistnum", ctypes.c_int),
        ("pcmreadcallback", ctypes.c_void_p),
        ("pcmsetposcallback", ctypes.c_void_p),
        ("nonblockcallback", ctypes.c_void_p),
        ("dlsname", ctypes.c_char_p),
        ("encryptionkey", ctypes.c_char_p),
        ("maxpolyphony", ctypes.c_int),
        ("userdata", ctypes.c_void_p),
        ("suggestedsoundtype", ctypes.c_int),
        ("fileuseropen", ctypes.c_void_p),
        ("fileuserclose", ctypes.c_void_p),
        ("fileuserread", ctypes.c_void_p),
        ("fileuserseek", ctypes.c_void_p),
        ("fileuserasyncread", ctypes.c_void_p),
        ("fileuserasynccancel", ctypes.c_void_p),
        ("fileuserdata", ctypes.c_void_p),
        ("filebuffersize", ctypes.c_int),
        ("channelorder", ctypes.c_int),
        ("channelmask", ctypes.c_uint),
        ("initialsoundgroup", ctypes.c_void_p),
        ("initialseekposition", ctypes.c_uint),
        ("initialseekpostype", ctypes.c_int),
        ("ignoresetfilesystem", ctypes.c_int),
        ("audioqueuepolicy", ctypes.c_uint),
        ("minmidigranularity", ctypes.c_uint),
        ("nonblockthreadid", ctypes.c_int),
        ("fsbguid", ctypes.c_void_p),
    ]


class FSBANK_SUBSOUND(ctypes.Structure):
    _fields_ = [
        ("fileNames", ctypes.c_void_p),        # const char* const*
        ("fileData", ctypes.c_void_p),         # const void* const*
        ("fileDataLengths", ctypes.c_void_p),  # const unsigned int*
        ("numFiles", ctypes.c_uint),
        ("overrideFlags", ctypes.c_uint),
        ("overrideQuality", ctypes.c_uint),
        ("desiredSampleRate", ctypes.c_float),
        ("percentOptimizedRate", ctypes.c_float),
    ]


class FSBANK_PROGRESSITEM(ctypes.Structure):
    _fields_ = [
        ("subSoundIndex", ctypes.c_int),
        ("threadIndex", ctypes.c_int),
        ("state", ctypes.c_int),
        ("stateData", ctypes.c_void_p),
    ]


class FmodBankError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# DLL loading
# ---------------------------------------------------------------------------

def _candidate_dirs():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    dirs = [
        script_dir,
        os.getcwd(),
        os.path.join(desktop, "fmodbank-cli"),
        os.path.join(desktop, "Fmod - 副本"),
        os.path.join(desktop, "Fmod_Bank_Tools"),
    ]
    out = []
    seen = set()
    for d in dirs:
        if d and d not in seen and os.path.isdir(d):
            seen.add(d)
            out.append(d)
    return out


class FmodDlls:
    """ctypes bindings to the original FMOD / FSBANK DLLs."""

    def __init__(self, dll_dir=None):
        dll_dir = self._locate(dll_dir)
        # Make the DLL's own directory visible so dependent codec DLLs
        # (e.g. libfsbvorbis64.dll for FSBANK) resolve.  Two mechanisms are
        # needed: add_dll_directory() covers implicit loader dependencies, and
        # PATH is what LoadLibrary("libfsbvorbis64.dll") searches at runtime.
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(dll_dir)
        if dll_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = dll_dir + os.pathsep + os.environ.get("PATH", "")
        self.dir = dll_dir

        fmod_path = self._find_in(dll_dir, "fmod64.dll")
        fsbank_path = self._find_in(dll_dir, "fsbank64.dll")
        if not fmod_path:
            raise FmodBankError("fmod64.dll not found. Use --dll-dir to point at the folder containing the DLLs.")
        if not fsbank_path:
            raise FmodBankError("fsbank64.dll not found. Use --dll-dir to point at the folder containing the DLLs.")

        self._fmod = ctypes.CDLL(fmod_path)
        self._fsbank = ctypes.CDLL(fsbank_path)
        self._bind_fmod()
        self._bind_fsbank()

    # -- locating --------------------------------------------------------
    @staticmethod
    def _find_in(dll_dir, name):
        p = os.path.join(dll_dir, name)
        return p if os.path.isfile(p) else None

    @classmethod
    def _locate(cls, dll_dir):
        if dll_dir:
            return os.path.abspath(dll_dir)
        for d in _candidate_dirs():
            if os.path.isfile(os.path.join(d, "fmod64.dll")):
                return d
        raise FmodBankError(
            "Could not locate fmod64.dll / fsbank64.dll. Place them next to this script, "
            "in the current directory, or pass --dll-dir."
        )

    # -- FMOD bindings ---------------------------------------------------
    def _bind_fmod(self):
        f = self._fmod
        f.FMOD_System_Create.restype = ctypes.c_int
        f.FMOD_System_Create.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        f.FMOD_System_Init.restype = ctypes.c_int
        f.FMOD_System_Init.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_void_p]
        f.FMOD_System_Release.restype = ctypes.c_int
        f.FMOD_System_Release.argtypes = [ctypes.c_void_p]
        f.FMOD_System_CreateSound.restype = ctypes.c_int
        f.FMOD_System_CreateSound.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint,
            ctypes.POINTER(FMOD_CREATESOUNDEXINFO), ctypes.POINTER(ctypes.c_void_p),
        ]
        f.FMOD_Sound_Release.restype = ctypes.c_int
        f.FMOD_Sound_Release.argtypes = [ctypes.c_void_p]
        f.FMOD_Sound_GetNumSubSounds.restype = ctypes.c_int
        f.FMOD_Sound_GetNumSubSounds.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
        f.FMOD_Sound_GetSubSound.restype = ctypes.c_int
        f.FMOD_Sound_GetSubSound.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
        f.FMOD_Sound_SeekData.restype = ctypes.c_int
        f.FMOD_Sound_SeekData.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        f.FMOD_Sound_GetDefaults.restype = ctypes.c_int
        f.FMOD_Sound_GetDefaults.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_int)]
        f.FMOD_Sound_GetFormat.restype = ctypes.c_int
        f.FMOD_Sound_GetFormat.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                                           ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
        f.FMOD_Sound_GetLength.restype = ctypes.c_int
        f.FMOD_Sound_GetLength.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint), ctypes.c_uint]
        f.FMOD_Sound_GetName.restype = ctypes.c_int
        f.FMOD_Sound_GetName.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        f.FMOD_Sound_ReadData.restype = ctypes.c_int
        f.FMOD_Sound_ReadData.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_uint)]

    # -- FSBANK bindings -------------------------------------------------
    def _bind_fsbank(self):
        b = self._fsbank
        b.FSBank_Init.restype = ctypes.c_int
        b.FSBank_Init.argtypes = [ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_char_p]
        b.FSBank_Release.restype = ctypes.c_int
        b.FSBank_Release.argtypes = []
        b.FSBank_Build.restype = ctypes.c_int
        b.FSBank_Build.argtypes = [
            ctypes.POINTER(FSBANK_SUBSOUND), ctypes.c_uint, ctypes.c_int, ctypes.c_uint,
            ctypes.c_uint, ctypes.c_char_p, ctypes.c_char_p,
        ]
        b.FSBank_FetchNextProgressItem.restype = ctypes.c_int
        b.FSBank_FetchNextProgressItem.argtypes = [ctypes.POINTER(ctypes.POINTER(FSBANK_PROGRESSITEM))]
        b.FSBank_ReleaseProgressItem.restype = ctypes.c_int
        b.FSBank_ReleaseProgressItem.argtypes = [ctypes.POINTER(FSBANK_PROGRESSITEM)]

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _check(rc, table, where):
        if rc != 0:
            raise FmodBankError("%s: %s" % (where, table.get(rc, "Unknown error (code %d)" % rc)))


# ---------------------------------------------------------------------------
# Bank parsing — port of bank_extract.cpp::extract
# ---------------------------------------------------------------------------

def _read_u32(data, pos):
    return struct.unpack_from("<I", data, pos)[0]


def parse_bank(data):
    """Parse a .bank and return a dict of FSB offsets/sizes.

    Returns None if the file is not a valid FEV bank.
    Mirrors bank_extract::extract() chunk walking exactly.
    """
    if len(data) < 0x24 or data[0:4] != b"RIFF":
        return None
    if data[0x08:0x0C] != b"FEV ":
        return None
    if _read_u32(data, 0x14) == 0:
        return None
    if data[0x1C:0x20] != b"LIST":
        return None

    pos = 0x20 + 4
    if data[pos:pos + 4] != b"PROJ" or data[pos + 4:pos + 8] != b"BNKI":
        return None
    pos += 8
    chunk_size = _read_u32(data, pos)
    pos += 4 + chunk_size  # skip PROJ/BNKI chunk body

    fsb_offset = [0]
    fsb_size = [0]

    while fsb_offset[0] == 0 and pos + 8 <= len(data):
        chunk_type = _read_u32(data, pos)
        chunk_size = _read_u32(data, pos + 4)
        pos += 8
        if chunk_type == 0xFFFFFFFF or chunk_size == 0xFFFFFFFF:
            return None

        if chunk_type == 0x48444E53:  # "SNDH"
            if chunk_size == 0:
                return None
            fsb_count = (chunk_size - 4) // 8
            sndh_unknown = _read_u32(data, pos)
            pos += 4
            fsb_offset = [_read_u32(data, pos + 8 * j) for j in range(fsb_count)]
            fsb_size = [_read_u32(data, pos + 4 + 8 * j) for j in range(fsb_count)]
            # NOTE: the original seeks past `chunk_size` again here; since the
            # loop exits as soon as fsb_offset[0] != 0 this has no effect.
            return {"fsb_offset": fsb_offset, "fsb_size": fsb_size, "fsb_count": fsb_count}

        pos += chunk_size

    if fsb_offset[0] == 0 or fsb_size[0] == 0:
        return None
    return {"fsb_offset": fsb_offset, "fsb_size": fsb_size, "fsb_count": len(fsb_offset)}


def extract_fsb(bank_path, fsb_dir):
    """Port of bank_extract::extract().  Writes <name>[i].fsb into fsb_dir.

    Returns (info, check) where check is the same code as the C++ version:
      0 invalid/error, 1 ok/unencrypted, 5 fsb encrypted (password required).
    """
    with open(bank_path, "rb") as fh:
        data = fh.read()

    info = parse_bank(data)
    if info is None:
        return None, 0

    bank_name = os.path.basename(bank_path)
    if bank_name.lower().endswith(".bank"):
        bank_name = bank_name[:-5]

    # check first FSB magic to detect encryption
    first_off = info["fsb_offset"][0]
    check = 1
    if first_off + 4 <= len(data) and data[first_off:first_off + 4] != b"FSB5":
        check = 5

    os.makedirs(fsb_dir, exist_ok=True)
    for j in range(info["fsb_count"]):
        off = info["fsb_offset"][j]
        size = info["fsb_size"][j]
        fsb_data = data[off:off + size]
        out_path = os.path.join(fsb_dir, "%s[%d].fsb" % (bank_name, j))
        with open(out_path, "wb") as fh:
            fh.write(fsb_data)
    return info, check


# ---------------------------------------------------------------------------
# WAV writing (port of ExtractWorker::writeWAVHeader)
# ---------------------------------------------------------------------------

def write_wav_header(fileobj, sample_rate, bits_per_sample, channels, data_len):
    fmt_chunk_len = 18          # 16 + 2 (cbSize) — same as the original
    format_type = 1             # PCM
    if bits_per_sample == 32:
        format_type = 3         # IEEE float (32-bit decoded samples)
    header_len = data_len + 38

    fileobj.write(b"RIFF")
    fileobj.write(struct.pack("<I", header_len))
    fileobj.write(b"WAVE")
    fileobj.write(b"fmt ")
    fileobj.write(struct.pack("<I", fmt_chunk_len))
    fileobj.write(struct.pack("<H", format_type))
    fileobj.write(struct.pack("<H", channels))
    fileobj.write(struct.pack("<I", sample_rate))
    block_align = channels * bits_per_sample // 8
    byte_rate = sample_rate * block_align
    fileobj.write(struct.pack("<I", byte_rate))
    fileobj.write(struct.pack("<H", block_align))
    fileobj.write(struct.pack("<H", bits_per_sample))
    fileobj.write(struct.pack("<H", 0))        # cbSize
    fileobj.write(b"data")
    fileobj.write(struct.pack("<I", data_len))


# ---------------------------------------------------------------------------
# Extract — decode FSB -> WAV with FMOD (port of ExtractWorker)
# ---------------------------------------------------------------------------

def _password_for(bank_dir, bank_name, explicit=None):
    """Return the encryption password for a bank, or None.

    Precedence (matches ExtractWorker::handlePasswordProtectedBank):
      <bank>.txt  >  password.txt
    """
    if explicit is not None:
        return explicit
    bank_txt = os.path.join(bank_dir, bank_name + ".txt")
    pass_txt = os.path.join(bank_dir, "password.txt")
    chosen = None
    if os.path.isfile(pass_txt):
        chosen = bank_txt if os.path.isfile(bank_txt) else pass_txt
    elif os.path.isfile(bank_txt):
        chosen = bank_txt
    if not chosen:
        return None
    with open(chosen, "r", encoding="utf-8", errors="replace") as fh:
        first = fh.readline().rstrip("\r\n")
    return first or None


def extract_fsb_to_wav(dlls, fsb_path, wav_dir, wav_name_base, out, quiet, password=None):
    """Decode a single FSB file into PCM wav files (ExtractWorker::processSubSounds)."""
    system = ctypes.c_void_p()
    exinfo = FMOD_CREATESOUNDEXINFO()
    exinfo.cbsize = ctypes.sizeof(FMOD_CREATESOUNDEXINFO)
    exinfo.length = 0
    if password:
        exinfo.encryptionkey = password.encode("utf-8")

    dlls._check(dlls._fmod.FMOD_System_Create(ctypes.byref(system)), FMOD_ERRORS, "FMOD_System_Create")
    try:
        rc = dlls._fmod.FMOD_System_Init(system, 1, FMOD_INIT_NORMAL, None)
        dlls._check(rc, FMOD_ERRORS, "FMOD_System_Init")
    except FmodBankError:
        dlls._fmod.FMOD_System_Release(system)
        raise

    sound = ctypes.c_void_p()
    name_b = os.path.abspath(fsb_path).encode("utf-8")
    try:
        rc = dlls._fmod.FMOD_System_CreateSound(system, name_b, FMOD_OPENONLY, ctypes.byref(exinfo), ctypes.byref(sound))
        if rc != FMOD_OK:
            raise FmodBankError("FMOD_System_CreateSound(%s): %s"
                                % (os.path.basename(fsb_path), FMOD_ERRORS.get(rc, "code %d" % rc)))

        num_sub = ctypes.c_int(0)
        dlls._check(dlls._fmod.FMOD_Sound_GetNumSubSounds(sound, ctypes.byref(num_sub)),
                    FMOD_ERRORS, "FMOD_Sound_GetNumSubSounds")
        n = num_sub.value

        os.makedirs(wav_dir, exist_ok=True)
        txt_names = []

        for j in range(n):
            sub = ctypes.c_void_p()
            try:
                dlls._check(dlls._fmod.FMOD_Sound_GetSubSound(sound, j, ctypes.byref(sub)),
                            FMOD_ERRORS, "FMOD_Sound_GetSubSound")
                dlls._check(dlls._fmod.FMOD_Sound_SeekData(sub, 0), FMOD_ERRORS, "FMOD_Sound_SeekData")

                freq = ctypes.c_float(0)
                priority = ctypes.c_int(0)
                dlls._check(dlls._fmod.FMOD_Sound_GetDefaults(sub, ctypes.byref(freq), ctypes.byref(priority)),
                            FMOD_ERRORS, "FMOD_Sound_GetDefaults")

                stype = ctypes.c_int(0)
                sformat = ctypes.c_int(0)
                channels = ctypes.c_int(0)
                bits = ctypes.c_int(0)
                dlls._check(dlls._fmod.FMOD_Sound_GetFormat(sub, ctypes.byref(stype), ctypes.byref(sformat),
                                                            ctypes.byref(channels), ctypes.byref(bits)),
                            FMOD_ERRORS, "FMOD_Sound_GetFormat")

                length = ctypes.c_uint(0)
                dlls._check(dlls._fmod.FMOD_Sound_GetLength(sub, ctypes.byref(length), FMOD_TIMEUNIT_PCMBYTES),
                            FMOD_ERRORS, "FMOD_Sound_GetLength")

                cname = ctypes.create_string_buffer(64)
                dlls._check(dlls._fmod.FMOD_Sound_GetName(sub, cname, 64), FMOD_ERRORS, "FMOD_Sound_GetName")
                sub_name = cname.value.decode("utf-8", "replace")
                if not sub_name:
                    sub_name = "sound_%d" % j

                base_name = sub_name
                file_name = base_name + ".wav"
                suffix = j
                while os.path.exists(os.path.join(wav_dir, file_name)):
                    sub_name = "%s_%d" % (base_name, suffix)
                    file_name = sub_name + ".wav"
                    suffix += 1

                data_len = length.value
                wav_path = os.path.join(wav_dir, file_name)
                with open(wav_path, "wb") as wav:
                    write_wav_header(wav, int(freq.value), bits.value, channels.value, data_len)
                    remaining = data_len
                    buf = ctypes.create_string_buffer(CHUNK_SIZE)
                    while remaining > 0:
                        want = min(CHUNK_SIZE, remaining)
                        got = ctypes.c_uint(0)
                        rc = dlls._fmod.FMOD_Sound_ReadData(sub, buf, want, ctypes.byref(got))
                        if rc != FMOD_OK:
                            raise FmodBankError("FMOD_Sound_ReadData(%s): %s"
                                                % (file_name, FMOD_ERRORS.get(rc, "code %d" % rc)))
                        if got.value == 0:
                            break
                        wav.write(buf.raw[:got.value])
                        remaining -= got.value

                dlls._fmod.FMOD_Sound_Release(sub)
                sub = None
                txt_names.append(sub_name + ".wav")
                if not quiet:
                    out("%d: (%s) [Extracting]" % (j, sub_name + ".wav"))
            except FmodBankError as e:
                out("[警告] 跳过无法解码的子音 #%d: %s" % (j, e))
                if sub.value:
                    dlls._fmod.FMOD_Sound_Release(sub)

        # write the <name>[i].txt list next to the wav folder
        txt_path = os.path.join(wav_dir, wav_name_base + ".txt")
        with open(txt_path, "w", encoding="utf-8") as fh:
            for t in txt_names:
                fh.write(t + "\n")
        return n
    finally:
        if sound.value:
            dlls._fmod.FMOD_Sound_Release(sound)
        dlls._fmod.FMOD_System_Release(system)


def cmd_extract(args, dlls, out=print):
    quiet = args.quiet
    targets = []
    if os.path.isdir(args.bank):
        targets = sorted(f for f in os.listdir(args.bank) if f.lower().endswith(".bank"))
        targets = [os.path.join(args.bank, f) for f in targets]
    else:
        targets = [args.bank]

    if not targets:
        raise FmodBankError("No .bank files found in %s" % args.bank)

    wav_dir = os.path.abspath(args.wav_dir)
    fsb_dir = os.path.abspath(args.fsb_dir)
    os.makedirs(wav_dir, exist_ok=True)
    os.makedirs(fsb_dir, exist_ok=True)

    for i, bank_path in enumerate(targets):
        if not os.path.isfile(bank_path):
            raise FmodBankError("Bank file not found: %s" % bank_path)
        bank_name = os.path.basename(bank_path)
        bank_base = bank_name[:-5] if bank_name.lower().endswith(".bank") else bank_name
        bank_dir = os.path.dirname(os.path.abspath(bank_path))
        if not quiet:
            out("***** Initializing Fmod Bank file - %s *****" % bank_name)

        info, check = extract_fsb(bank_path, fsb_dir)
        if check == 0:
            out("Error extracting bank file: %s" % bank_name)
            continue
        if check == 2:
            out("Error, can't find any fsb audio in this bank file: %s" % bank_name)
            continue

        password = None
        if check == 5:
            password = _password_for(bank_dir, bank_base, args.password)
            if password is None:
                out("Can't find password.txt or %s.txt with password for decryption." % bank_base)
                continue
            if not quiet:
                out("Decrypting bank file with password: %s" % password)

        for j in range(info["fsb_count"]):
            fsb_path = os.path.join(fsb_dir, "%s[%d].fsb" % (bank_base, j))
            if not os.path.isfile(fsb_path):
                out("Error, %s[%d].fsb file is missing !!!" % (bank_base, j))
                continue
            if not quiet:
                out("Extracting fsb file - %s" % os.path.basename(fsb_path))
            wav_subdir = os.path.join(wav_dir, "%s[%d]" % (bank_base, j))
            extract_fsb_to_wav(dlls, fsb_path, wav_subdir, "%s[%d]" % (bank_base, j),
                               out, quiet, password)

    if not quiet:
        out("Extracting Bank files has finished.")


# ---------------------------------------------------------------------------
# Rebuild — FSBANK encode + bank re-assembly (port of RebuildWorker)
# ---------------------------------------------------------------------------

def _drain_progress(dlls, out):
    """Fetch and report FSBANK progress items (RebuildWorker::bankProgress)."""
    while True:
        item_p = ctypes.POINTER(FSBANK_PROGRESSITEM)()
        rc = dlls._fsbank.FSBank_FetchNextProgressItem(ctypes.byref(item_p))
        if rc != 0 or not item_p:
            break
        item = item_p.contents
        if item.state == FSBANK_STATE_FINISHED and item.subSoundIndex != -1:
            out("  [Processed %d]" % item.subSoundIndex)
        elif item.state == FSBANK_STATE_WARNING:
            out("Warning, there is a issue with one of the wav files.")
        elif item.state == FSBANK_STATE_FAILED:
            out("fsb file failed to build.")
        dlls._fsbank.FSBank_ReleaseProgressItem(item_p)


def build_fsb(dlls, wav_files, out_fsb, format_id, quality, build_flags, threads, cache_dir, encrypt_key=None, out=print):
    """Encode a list of wav files into one FSB (FSBank_Build)."""
    os.makedirs(cache_dir, exist_ok=True)
    rc = dlls._fsbank.FSBank_Init(FSBANK_FSBVERSION_FSB5, FSBANK_INIT_GENERATEPROGRESSITEMS,
                                  threads, cache_dir.encode("utf-8"))
    if rc != 0:
        raise FmodBankError("FSBank_Init: " + FSBANK_ERRORS.get(rc, "code %d" % rc))

    try:
        n = len(wav_files)
        # keep the encoded path bytes alive for the duration of FSBank_Build
        enc = [w.encode("utf-8") for w in wav_files]
        # FSBANK_SUBSOUND.fileNames is `const char* const*` -> an array of
        # char pointers. Each subsound carries one filename (numFiles = 1).
        ptr_arrays = [(ctypes.c_char_p * 1)(b) for b in enc]
        arr = (FSBANK_SUBSOUND * n)()
        for i in range(n):
            arr[i].fileNames = ctypes.cast(ptr_arrays[i], ctypes.c_void_p)
            arr[i].numFiles = 1

        key_b = encrypt_key.encode("utf-8") if encrypt_key else None
        out_b = out_fsb.encode("utf-8")
        rc = dlls._fsbank.FSBank_Build(arr, n, format_id, build_flags,
                                       quality, key_b, out_b)
        if rc != 0:
            raise FmodBankError("FSBank_Build: " + FSBANK_ERRORS.get(rc, "code %d" % rc))
        _drain_progress(dlls, out)
    finally:
        dlls._fsbank.FSBank_Release()


def parse_bank_for_rebuild(data):
    """Port of RebuildWorker::bankRebuild()'s header walk.

    Returns a dict with sndh offsets/sizes, snd locations/buffers, fsbCount,
    sndh_location, first-fsb offset, or None on parse failure.
    """
    if len(data) < 0x24 or data[0:4] != b"RIFF":
        return None
    if data[0x08:0x0C] != b"FEV ":
        return None
    if _read_u32(data, 0x14) == 0:
        return None
    if data[0x1C:0x20] != b"LIST":
        return None

    pos = 0x20 + 4
    if data[pos:pos + 4] != b"PROJ" or data[pos + 4:pos + 8] != b"BNKI":
        return None
    pos += 8
    chunk_size = _read_u32(data, pos)
    pos += 4 + chunk_size

    fsb_offset = [0]
    fsb_size = [0]
    snd_location = [0]
    snd_buffer = [0]
    fsb_count = 1
    sndh_unknown = 0
    sndh_location = 0

    while snd_location[0] == 0 and pos + 8 <= len(data):
        chunk_type = _read_u32(data, pos)
        chunk_size = _read_u32(data, pos + 4)
        pos += 8
        if chunk_type == 0xFFFFFFFF or chunk_size == 0xFFFFFFFF:
            return None

        if chunk_type == 0x48444E53:  # "SNDH"
            fsb_count = (chunk_size - 4) // 8
            fsb_offset = [0] * fsb_count
            fsb_size = [0] * fsb_count
            sndh_unknown = _read_u32(data, pos)
            pos += 4
            sndh_location = pos  # file.pos() right after reading sndh_unknown
            for j in range(fsb_count):
                fsb_offset[j] = _read_u32(data, pos)
                fsb_size[j] = _read_u32(data, pos + 4)
                pos += 8
            continue  # skips the trailing seek in the original

        if chunk_type == 0x4C425453:  # "STBL"
            current_pos = pos
            if chunk_size != 0:
                hash_pos = current_pos + chunk_size
                if hash_pos + 4 <= len(data):
                    hash_val = _read_u32(data, hash_pos)
                    if hash_val not in (0x20444E53, 0x48534148):  # "SND ", "HASH"
                        chunk_size += 1
            pos = current_pos + chunk_size
            continue

        if chunk_type == 0x20444E53:  # "SND "
            snd_location = [0] * fsb_count
            snd_buffer = [0] * fsb_count
            snd_location[0] = pos - 8
            snd_buffer[0] = chunk_size - fsb_size[0]
            if fsb_count > 1:
                for j in range(fsb_count - 1):
                    snd_location[j + 1] = fsb_offset[j] + fsb_size[j]
                    p2 = snd_location[j + 1] + 4
                    if p2 + 4 <= len(data):
                        snd_buffer[j + 1] = _read_u32(data, p2) - fsb_size[j + 1]
            # falls through to the trailing seek then loop exits

        pos += chunk_size

    if fsb_offset[0] == 0 or fsb_size[0] == 0:
        return None
    if sndh_location == 0 or snd_location[0] == 0:
        return None
    return {
        "fsb_offset": fsb_offset,
        "fsb_size": fsb_size,
        "fsb_count": fsb_count,
        "snd_location": snd_location,
        "snd_buffer": snd_buffer,
        "sndh_location": sndh_location,
    }


def rebuild_bank_file(dlls, bank_path, wav_dir, fsb_dir, build_dir, options, out=print, quiet=False):
    """Rebuild one bank.  Port of RebuildWorker::rebuild_bank + bankRebuild."""
    bank_name = os.path.basename(bank_path)
    bank_base = bank_name[:-5] if bank_name.lower().endswith(".bank") else bank_name
    bank_dir = os.path.dirname(os.path.abspath(bank_path))

    if not os.path.isfile(bank_path):
        raise FmodBankError("Can't find original bank: %s" % bank_path)

    with open(bank_path, "rb") as fh:
        bank_data = fh.read()
    info = parse_bank_for_rebuild(bank_data)
    if info is None:
        raise FmodBankError("Failed to parse bank header: %s" % bank_name)

    if not quiet:
        out("Fmod Bank file: %s.bank" % bank_base)
        out("Format: %s" % options["format_name"])
        out("Thread Count: %d" % options["threads"])
        out("ReBuilding %s.bank has started, Please wait....." % bank_base)

    # encryption password (rebuild path: <bank>.txt wins over password.txt)
    password = options["password"]
    if password is None:
        bank_txt = os.path.join(bank_dir, bank_base + ".txt")
        pass_txt = os.path.join(bank_dir, "password.txt")
        if os.path.isfile(bank_txt):
            password = _first_line(bank_txt)
        elif os.path.isfile(pass_txt):
            password = _first_line(pass_txt)
    if password is not None and not quiet:
        out("Encrypting bank file with password: %s" % password)

    fsb_count = info["fsb_count"]

    # 1. build each FSB from its wav list
    for j in range(fsb_count):
        base = "%s[%d]" % (bank_base, j)
        txt_path = _find_wav_txt(wav_dir, base)
        if txt_path is None:
            raise FmodBankError("Missing wav list: %s[%d].txt (looked in %s)" % (bank_base, j, wav_dir))
        wav_files = _read_list(txt_path)
        wav_full = [os.path.join(wav_dir, base, w) for w in wav_files]
        missing = [w for w in wav_full if not os.path.isfile(w)]
        if missing:
            raise FmodBankError("Missing wav file(s): %s" % ", ".join(missing))
        fsb_out = os.path.join(fsb_dir, "%s.fsb" % base)
        build_fsb(dlls, wav_full, fsb_out, options["format"], options["quality"],
                  options["build_flags"], options["threads"], options["cache_dir"],
                  password, out)

    # 2. re-assemble the bank (port of bankRebuild)
    _assemble_bank(bank_data, bank_path, info, fsb_dir, build_dir, bank_base)


def _assemble_bank(bank_data, bank_path, info, fsb_dir, build_dir, bank_base):
    fsb_count = info["fsb_count"]
    sndh_offset = info["fsb_offset"]
    snd_buffer = info["snd_buffer"]
    sndh_location = info["sndh_location"]
    snd_location = info["snd_location"]

    header = bank_data[:sndh_offset[0]]

    fsb_sizes = []
    for i in range(fsb_count):
        p = os.path.join(fsb_dir, "%s[%d].fsb" % (bank_base, i))
        if not os.path.isfile(p):
            raise FmodBankError("fsb file does not exist %s" % p)
        fsb_sizes.append(os.path.getsize(p))

    if fsb_count > 1:
        for i in range(fsb_count - 1):
            sndh_offset[i + 1] = sndh_offset[i] + fsb_sizes[i] + snd_buffer[i + 1] + 8

    os.makedirs(build_dir, exist_ok=True)
    out_path = os.path.join(build_dir, os.path.basename(bank_path))
    with open(out_path, "wb") as fh:
        fh.write(header)

        # update SNDH offsets/sizes table
        fh.seek(sndh_location)
        for i in range(fsb_count):
            fh.write(struct.pack("<I", sndh_offset[i]))
            fh.write(struct.pack("<I", fsb_sizes[i]))

        # write each SND chunk: "SND " + size + pad + fsb data
        fh.seek(snd_location[0])
        for i in range(fsb_count):
            fsb_path = os.path.join(fsb_dir, "%s[%d].fsb" % (bank_base, i))
            with open(fsb_path, "rb") as fin:
                fsb_data = fin.read()
            fh.write(b"SND ")
            fh.write(struct.pack("<I", fsb_sizes[i] + snd_buffer[i]))
            if snd_buffer[i] != 0:
                fh.write(b"\0" * snd_buffer[i])
            fh.write(fsb_data)

        # fix RIFF size
        header_size = fh.tell() - 8
        fh.seek(4)
        fh.write(struct.pack("<I", header_size))


def _first_line(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.readline().rstrip("\r\n")


def _find_wav_txt(wav_dir, base):
    """Locate the wav list `<base>.txt` produced by extract.

    The original tool writes it inside the sub-folder (`wav_dir/<base>/<base>.txt`);
    also accept a copy placed directly in `wav_dir` for convenience.
    """
    for cand in (os.path.join(wav_dir, base + ".txt"),
                 os.path.join(wav_dir, base, base + ".txt")):
        if os.path.isfile(cand):
            return cand
    for root, _, files in os.walk(wav_dir):
        for f in files:
            if f.endswith(".txt") and f[:-4] == base:
                return os.path.join(root, f)
    return None


def _read_list(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return [line.rstrip("\r\n") for line in fh if line.strip() != ""]


def cmd_rebuild(args, dlls, out=print):
    quiet = args.quiet
    wav_dir = os.path.abspath(args.wav_dir)
    fsb_dir = os.path.abspath(args.fsb_dir)
    build_dir = os.path.abspath(args.build_dir)
    os.makedirs(fsb_dir, exist_ok=True)

    if args.format == "vorbis":
        format_id, format_name = FSBANK_FORMAT_VORBIS, "Vorbis"
    elif args.format == "pcm":
        format_id, format_name = FSBANK_FORMAT_PCM, "PCM"
    elif args.format == "fadpcm":
        format_id, format_name = FSBANK_FORMAT_FADPCM, "FADPCM"
    else:
        raise FmodBankError("Unknown format: %s" % args.format)

    build_flags = 0
    if args.no_syncpoints:
        build_flags |= FSBANK_BUILD_DISABLESYNCPOINTS
    if args.no_loop:
        build_flags |= FSBANK_BUILD_DONTLOOP
    if args.no_names:
        build_flags |= FSBANK_BUILD_FSB5_DONTWRITENAMES
    if args.write_peak:
        build_flags |= FSBANK_BUILD_WRITEPEAKVOLUME

    options = {
        "format": format_id,
        "format_name": format_name,
        "quality": args.quality,
        "threads": args.threads,
        "build_flags": build_flags,
        "cache_dir": os.path.abspath(args.cache_dir),
        "password": args.password,
    }

    if os.path.isdir(args.bank):
        targets = sorted(f for f in os.listdir(args.bank) if f.lower().endswith(".bank"))
        targets = [os.path.join(args.bank, f) for f in targets]
    else:
        targets = [args.bank]

    if not targets:
        raise FmodBankError("No .bank files found in %s" % args.bank)

    for bank_path in targets:
        rebuild_bank_file(dlls, bank_path, wav_dir, fsb_dir, build_dir, options, out, quiet)

    if not quiet:
        out("Rebuilding Bank files has finished.")


def cmd_info(args, dlls, out=print):
    for p in ([args.bank] if os.path.isfile(args.bank) else
              sorted(os.path.join(args.bank, f) for f in os.listdir(args.bank) if f.lower().endswith(".bank"))):
        with open(p, "rb") as fh:
            data = fh.read()
        info = parse_bank(data)
        name = os.path.basename(p)
        if info is None:
            out("%-40s  <invalid / not an FEV bank>" % name)
            continue
        encrypted = data[info["fsb_offset"][0]:info["fsb_offset"][0] + 4] != b"FSB5" \
            if info["fsb_offset"][0] + 4 <= len(data) else False
        total = sum(info["fsb_size"])
        out("%-40s  fsb=%d  size=%.1f MB  %s"
            % (name, info["fsb_count"], total / 1048576.0, "ENCRYPTED" if encrypted else ""))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dll-dir", metavar="DIR",
                        help="folder containing fmod64.dll / fsbank64.dll / libfsbvorbis64.dll "
                             "(default: auto-detect next to the script / in cwd)")
    common.add_argument("--quiet", action="store_true", help="only print errors")

    ap = argparse.ArgumentParser(
        prog="fmodbank",
        parents=[common],
        description="CLI wrapper for FMOD Bank Tools — extract/rebuild Fmod .bank files "
                    "using the original fmod64.dll / fsbank64.dll.",
    )
    sub = ap.add_subparsers(dest="command", required=True)

    # extract
    ex = sub.add_parser("extract", parents=[common], help="extract .bank file(s) to wav")
    ex.add_argument("bank", help="a .bank file, or a directory of .bank files")
    ex.add_argument("-o", "--wav-dir", default="./wav", help="wav output dir (default ./wav)")
    ex.add_argument("--fsb-dir", default="./fsb", help="fsb output dir (default ./fsb)")
    ex.add_argument("-p", "--password", help="encryption password (overrides auto-detected <bank>.txt/password.txt)")
    ex.set_defaults(func=cmd_extract)

    # rebuild
    rb = sub.add_parser("rebuild", parents=[common], help="rebuild .bank file(s) from edited wav files")
    rb.add_argument("bank", help="a .bank file, or a directory of .bank files")
    rb.add_argument("-w", "--wav-dir", default="./wav", help="wav dir containing <bank>[i]/ folders and .txt lists (default ./wav)")
    rb.add_argument("--fsb-dir", default="./fsb", help="fsb dir (default ./fsb)")
    rb.add_argument("-o", "--build-dir", default="./build", help="output dir for rebuilt .bank (default ./build)")
    rb.add_argument("--cache-dir", default="./fsbcache", help="FSBANK cache dir (default ./fsbcache)")
    rb.add_argument("--format", choices=["vorbis", "pcm", "fadpcm"], default="vorbis", help="encode format (default vorbis)")
    rb.add_argument("--quality", type=int, default=92, help="encode quality 0-100 (default 92, vorbis only)")
    rb.add_argument("-cpu", "--threads", type=int, default=default_cpu_threads(),
                    help="编码线程数（默认自动用一半 CPU 核心，如 -cpu 4）")
    rb.add_argument("-p", "--password", help="encryption password (overrides auto-detected files)")
    rb.add_argument("--no-syncpoints", action="store_true", help="disable syncpoint encoding")
    rb.add_argument("--no-loop", action="store_true", help="disable seamless loop encoding")
    rb.add_argument("--no-names", action="store_true", help="do not write subsound names into the FSB")
    rb.add_argument("--write-peak", action="store_true", help="write peak volume to the FSB")
    rb.set_defaults(func=cmd_rebuild)

    # info
    inf = sub.add_parser("info", parents=[common], help="show FSB layout of .bank file(s) without extracting")
    inf.add_argument("bank", help="a .bank file, or a directory of .bank files")
    inf.set_defaults(func=cmd_info)

    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        dlls = FmodDlls(args.dll_dir)
        args.func(args, dlls)
    except FmodBankError as e:
        print("Error: %s" % e, file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print("Error: %s" % e, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
