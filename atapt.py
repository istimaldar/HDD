#!/usr/bin/env python3

import ctypes
import fcntl
import string
import os
import time

# ATA Commands
ATA_IDENTIFY = 0xEC
ATA_READ_SECTORS = 0x20
ATA_READ_SECTORS_EXT = 0x24
ATA_READ_VERIFY_SECTORS = 0x40
ATA_READ_VERIFY_SECTORS_EXT = 0x42
ATA_WRITE_SECTORS = 0x30
ATA_WRITE_SECTORS_EXT = 0x34
ATA_SMART_COMMAND = 0xB0
SMART_READ_VALUES = 0xD0
SMART_READ_THRESHOLDS = 0xD1

SMART_LBA = 0xC24F00

# scsi/sg.h
SG_DXFER_NONE = -1          # SCSI Test Unit Ready command
SG_DXFER_TO_DEV = -2        # SCSI WRITE command
SG_DXFER_FROM_DEV = -3      # SCSI READ command

ASCII_S = 83
SG_IO = 0x2285

SPC_SK_ILLEGAL_REQUEST = 0x5

suppotred_ata = {16: 'Supports ATA/ATAPI-4', 32: 'Supports ATA/ATAPI-5' ,64: 'Supports ATA/ATAPI-6',
                 128: 'Supports ATA/ATAPI-7', 256: 'Supports ATA8/ACS'}

class ataCmd(ctypes.Structure):
    """
    This structure descdibed in http://www.t10.org/ftp/t10/document.04/04-262r8.pdf
    """
    _pack_ = 1
    _fields_ = [
        ('opcode', ctypes.c_ubyte),
        ('protocol', ctypes.c_ubyte),
        ('flags', ctypes.c_ubyte),
        ('features', ctypes.c_ushort),
        ('sector_count', ctypes.c_ushort),
        ('lba_h_low', ctypes.c_ubyte),
        ('lba_low', ctypes.c_ubyte),
        ('lba_h_mid', ctypes.c_ubyte),
        ('lba_mid', ctypes.c_ubyte),
        ('lba_h_high', ctypes.c_ubyte),
        ('lba_high', ctypes.c_ubyte),
        ('device', ctypes.c_ubyte),
        ('command', ctypes.c_ubyte),
        ('control', ctypes.c_ubyte)]

class GeneralConfiguration(ctypes.Structure):

    _pack_ =1
    _fields_ = [

    ]

class _IDENTIFY_DEVICE_DATA(ctypes.Structure):

    _pack_ =1
    _fields_ = [

    ]

class sgioHdr(ctypes.Structure):
    """
    This structure descibed in scsi/sg.h
    """
    _pack_ = 1
    _fields_ = [
        ('interface_id', ctypes.c_int),
        ('dxfer_direction', ctypes.c_int),
        ('cmd_len', ctypes.c_ubyte),
        ('mx_sb_len', ctypes.c_ubyte),
        ('iovec_count', ctypes.c_ushort),
        ('dxfer_len', ctypes.c_uint),
        ('dxferp', ctypes.c_void_p),
        ('cmdp', ctypes.c_void_p),
        ('sbp', ctypes.c_void_p),
        ('timeout', ctypes.c_uint),
        ('flags', ctypes.c_uint),
        ('pack_id', ctypes.c_int),
        ('usr_ptr', ctypes.c_void_p),
        ('status', ctypes.c_ubyte),
        ('masked_status', ctypes.c_ubyte),
        ('msg_status', ctypes.c_ubyte),
        ('sb_len_wr', ctypes.c_ubyte),
        ('host_status', ctypes.c_ushort),
        ('driver_status', ctypes.c_ushort),
        ('resid', ctypes.c_int),
        ('duration', ctypes.c_uint),
        ('info', ctypes.c_uint)]


class ataptError(Exception):
    """
    Indicates exceptions raised by a atapt class.
    """
    pass


class initFalied(ataptError):
    """
    Raised on atapt initialization falied
    """

    def __init__(self, error):
        ataptError.__init__(
            self, "ATA Pass-Through initialisation falied! reason: " + error)


class sgioFalied(ataptError):
    """
    Raised on SGIO prepare falied
    """

    def __init__(self, error):
        ataptError.__init__(self, "SGIO prepare falied! reason: " + error)


class senseError(ataptError):
    """
    Raised on checkSense found error
    """

    def __init__(self, error):
        ataptError.__init__(self, "Sense check error! reason: " + error)


def swap16(x):
    return ((x << 8) & 0xFF00) | ((x >> 8) & 0x00FF)


def swapString(strg):
    s = []
    for x in range(0, len(strg) - 1, 2):
        s.append(chr(strg[x + 1]))
        s.append(chr(strg[x]))
    return ''.join(s).strip()


def printBuf(buf):
    """
    Print buf xxd like style
    """
    if buf is None:
        raise ataptError("Got None instead buffer")
    for l in range(0, int(ctypes.sizeof(buf) / 16)):
        intbuf = []
        for i in range(0, 16):
            intbuf.append(
                chr(int.from_bytes(buf[16 * l + i], byteorder='little')))
        buf2 = [('%02x' % ord(i)) for i in intbuf]
        print('{0}: {1:<39}  {2}'.format(('%07x' % (l * 16)),
                                         ' '.join([''.join(buf2[i:i + 2])
                                                   for i in range(0, len(buf2), 2)]),
                                         ''.join([c if c in string.printable[:-5] else '.' for c in intbuf])))


class atapt:
    """
    Main ATA Pass-Through class
    """

    def __init__(self, dev):
        self.smart = {}
        self.ssd = 0
        self.duration = 0
        self.timeout = 1000
        self.readCommand = ATA_READ_SECTORS
        self.verifyCommand = ATA_READ_VERIFY_SECTORS
        self.writeCommand = ATA_WRITE_SECTORS
        self.sense = ctypes.c_buffer(64)
        self.checkExists(dev)
        self.devIdentify()

    def checkSense(self):
        response_code = 0x7f & int.from_bytes(
            self.sense[0], byteorder='little')
        if response_code >= 0x72:
            sense_key = 0xf & int.from_bytes(self.sense[1], byteorder='little')
            asc = self.sense[2]
            ascq = self.sense[3]
        else:
            raise senseError("No sense")
        if sense_key == SPC_SK_ILLEGAL_REQUEST:
            if asc == b'\x20' and ascq == b'\x00':
                raise senseError("ATA PASS-THROUGH not supported")
            else:
                raise senseError("Bad field in cdb")
        else:
            if self.sense[8] == b'\x09':
                self.ata_error = int.from_bytes(
                    self.sense[11], byteorder='little')
                self.ata_status = int.from_bytes(
                    self.sense[21], byteorder='little')

    def clearSense(self):
        for i in range(64):
            self.sense[i] = 0

    def prepareSgio(self, cmd, feature, count, lba, buf):
        if cmd in [ATA_IDENTIFY, ATA_READ_SECTORS, ATA_READ_SECTORS_EXT, ATA_SMART_COMMAND]:
            if buf is None:
                raise sgioFalied("Got None instead buffer")
            direction = SG_DXFER_FROM_DEV
            buf_len = ctypes.sizeof(buf)
            buf_p = ctypes.cast(buf, ctypes.c_void_p)
            prot = 4 << 1  # PIO Data-In
        elif cmd in [ATA_WRITE_SECTORS, ATA_WRITE_SECTORS_EXT]:
            if buf is None:
                raise sgioFalied("Got None instead buffer")
            direction = SG_DXFER_TO_DEV
            buf_len = ctypes.sizeof(buf)
            buf_p = ctypes.cast(buf, ctypes.c_void_p)
            prot = 5 << 1  # PIO Data-Out
        elif cmd in [ATA_READ_VERIFY_SECTORS, ATA_READ_VERIFY_SECTORS_EXT]:
            direction = SG_DXFER_NONE
            buf_len = 0
            buf_p = None
            prot = 3 << 1  # Non-data
        else:
            raise sgioFalied("Unknown ATA command : 0x%0.2X" % cmd)
        if cmd in [ATA_READ_SECTORS_EXT, ATA_WRITE_SECTORS_EXT, ATA_READ_VERIFY_SECTORS_EXT]:
            prot = prot | 1  # + EXTEND
        sector_lba = lba.to_bytes(6, byteorder='little')
        ata_cmd = ataCmd(opcode=0x85,  # ATA PASS-THROUGH (16)
                         protocol=prot,
                         # flags field
                         # OFF_LINE = 0 (0 seconds offline)
                         # CK_COND = 1 (copy sense data in response)
                         # T_DIR = 1 (transfer from the ATA device)
                         # BYT_BLOK = 1 (length is in blocks, not bytes)
                         # T_LENGTH = 2 (transfer length in the SECTOR_COUNT
                         # field)
                         flags=0x2e,
                         features=swap16(feature),
                         sector_count=swap16(count),
                         lba_h_low=sector_lba[3], lba_low=sector_lba[0],
                         lba_h_mid=sector_lba[4], lba_mid=sector_lba[1],
                         lba_h_high=sector_lba[5], lba_high=sector_lba[2],
                         device=1 << 6, # Enable LBA on ATA-5 and older drives
                         command=cmd,
                         control=0)

        sgio = sgioHdr(interface_id=ASCII_S, dxfer_direction=direction,
                       cmd_len=ctypes.sizeof(ata_cmd),
                       mx_sb_len=ctypes.sizeof(self.sense), iovec_count=0,
                       dxfer_len=buf_len,
                       dxferp=buf_p,
                       cmdp=ctypes.addressof(ata_cmd),
                       sbp=ctypes.cast(self.sense, ctypes.c_void_p), timeout=self.timeout,
                       flags=0, pack_id=0, usr_ptr=None, status=0, masked_status=0,
                       msg_status=0, sb_len_wr=0, host_status=0, driver_status=0,
                       resid=0, duration=0, info=0)

        return sgio

    def checkExists(self, dev):
        if not os.path.exists(dev):
            raise initFalied("Device not exists")
        self.dev = dev

    def devIdentify(self):
        buf = ctypes.c_buffer(512)
        sgio = self.prepareSgio(ATA_IDENTIFY, 0, 0, 0, buf)
        self.clearSense()
        with open(self.dev, 'r') as fd:
            try:
                startTime = time.time()
                fcntl.ioctl(fd, SG_IO, ctypes.addressof(sgio))
            except IOError:
                raise sgioFalied("fcntl.ioctl falied")
        self.duration = (time.time() - startTime) * 1000
        #self.checkSense()
        self.ata_support = self.supported_ata(buf[80])
        self.mem_support = self.supported_mem(buf[99])
        self.serial = swapString(buf[20:40])
        self.firmware = swapString(buf[46:53])
        self.model = swapString(buf[54:93])
        self.sectors = int.from_bytes(buf[200] + buf[201] + buf[202] + buf[203] +
                                      buf[204] + buf[205] + buf[206] + buf[207], byteorder='little')
        if self.sectors > 268435456:
            self.readCommand = ATA_READ_SECTORS_EXT
            self.verifyCommand = ATA_READ_VERIFY_SECTORS_EXT
            self.writeCommand = ATA_WRITE_SECTORS_EXT

        self.size = self.sectors / 2097152
        self.rpm = int.from_bytes(buf[434] + buf[435], byteorder='little')
        if self.rpm == 1:
            self.ssd = 1

        # word 106 bit 12 "Device Logical Sector longer than 256 Words"
        if not int.from_bytes(buf[212] + buf[213], byteorder='little') & 0x1000:
            self.logicalSectorSize = 512
        else:
            self.logicalSectorSize = int.from_bytes(buf[234] + buf[235] + buf[236] + buf[237], byteorder='little')

        # word 106 bit 13 "Device has multiple logical sectors per physical sector"
        if not int.from_bytes(buf[212] + buf[213], byteorder='little') & 0x2000:
            self.physicalSectorSize = self.logicalSectorSize
        else:
            self.physicalSectorSize = (1 << (int.from_bytes(
                buf[212] + buf[213], byteorder='little') & 0x0F)) * self.logicalSectorSize

    def supported_ata(self, lower_byte):
        supported = []
        for key in suppotred_ata:
            if ord(lower_byte) & key:
                supported.append(suppotred_ata[key])
        return supported

    def supported_mem(self, data):
        supported = ['PIO']
        suppotred_mem = {1: "DMA", 2: "LBA"}
        for key in suppotred_mem:
            if ord(data) & key:
                supported.append(suppotred_mem[key])
        return supported
