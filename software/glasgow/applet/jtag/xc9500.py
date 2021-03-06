# Ref: XAPP069 Using the XC9500/XL/XV JTAG Boundary Scan Interface
# Ref: XC9572XL BSDL files
# Ref: black box reverse engineering of XC9572XL by whitequark

# JTAG IR commands
# ----------------
#
# Beyond the documentation in XAPP069, observations given the information from BSDL files:
#
#   * ISPEX (also called CONLD) selects BYPASS[1].
#   * ISPEN, ISPENC select ISPENABLE[6].
#   * FERASE, FBULK, FBLANK select ISADDRESS[18].
#   * FPGMI, FVFYI select ISDATA[34].
#   * FPGM, FVFY select ISCONFIGURATION[50].
#   * ISPENC is encoded like a "command variant" of ISPEN (differs by LSB). Not documented,
#     function unclear.
#   * FBLANK is encoded rather unlike FERASE and FBULK. Not documented, function unclear.
#
# Functional observations from black-box hardware reverse engineering:
#   * There is no need to shift DR after selecting ISPENABLE. ISPENABLE is shifted and completely
#     ignored by SVF files.
#   * The general format of DR seems to be valid bit, strobe bit, then payload. FPGMI, FVFYI
#     use 32-bit data as payload; FERASE, FBULK, FBLANK use 16-bit address as payload;
#     FPGM, FVFY use a concatenated data plus address payload.
#
# Functional observations from ISE SVF files:
#   * Check for Read/Write Protection appears to use the value captured in Capture-IR.
#     It appears that one of the three MSBs will be set in a protected device.
#   * FVFY uses strobe bit as word read strobe. FPGM uses strobe bit as block (see below on blocks)
#     write strobe; an entire block is loaded into a buffer first, and then written in one cycle.
#   * Check for FBULK and FPGM success (and probably FERASE success too) is a check for valid bit
#     being high and strobe bit being low.
#   * FBULK needs 200 ms / 200k cycles, and FPGM w/ strobe needs 20 ms / 20 k cycles in Run-Test.
#
# Bitstream structure
# -------------------
#
# From the Xilinx JED files, the XC9572XL bitstream has 46656 individual fuse bits. The bitstream
# JED file uses two type of JED L fields, we will call them "4x8" L-field:
#    L0000000 00000000 00000000 00000000 00000000*
# and "4x6" L-field:
#    L0000288 000000 000000 000000 000000*
# The L-fields are organized into blocks of 15 L-fields, made from 9 4x8 L-fields followed
# by 6 4x6 L-fields. The entire XC9572XL bitstream consists of exactly 108 of such blocks.
# This can be verified by matching the JED file against a regexp:
#    (L\d{7}( [01]{8}){4}\*\n){9}(L\d{7}( [01]{6}){4}\*\n){6}
# There are 1620 L-fields in total.
#
# From reverse engineering, the XC9572XL bitstream is organized as 1620x32. This is determined
# because after 1620 reads from FVFYI, the bitstream starts to repeat.
#
# Conjecture (high confidence): each JED L-field maps to exactly one chip bitstream word.
#
# On 0th read, the first 2 words on my XC9572XL read as:
#   11001001110010011100100111001001
#   01001010010010100000000101001010
# and the next 34 words (for 36 words total) read as zero.
#
# On 1th and further reads, the first 20 words read as:
#   00000000000000000000000000000000
#   00000000000110000000000000000000
#   00000000001000000000000000000000
#   00000000000000000000000000000000
#   00000000000000000000000000000000
#   00000000000100000000000000011010
#   00000000001000000000000000000000
#   00000000000000010000000000000000
#   00000000001000000000000000000000
#   00000000000000000000000000000000
#   00000000001000000000000000001011
#   00000000000000000000000000000000
#   00000000001000000000000000000000
#   00000000000100000000000000000000
#   00000000000000000000000000000000
#   00000000000010000000000000001001
#   00000000000000000000000000000000
#   00000000000000000010000000000000
#   00000000001000000000000000000000
#   00000000001000000000000000000000
# and the next 14 words (for 36 words total) read as zero. The 20 different words from 1th read
# or any non-degenerate subset thereof do not appear in that sequence anywhere else in
# the bitstream.
#
# Conjecture (medium confidence): first several FVFYI reads (at least 20) actually happen from
# some sort of auxiliary memory. Moreover, these reads are not *prefixed* to the actual bitstream,
# but in fact *replace* a part of the actual bistream.
#
# Looking only at words that correspond to 6x4 L-fields, these words appear like this:
#   00010111000000000000000000000000
#   00010110000000100000000000000000
#   00010110001000000010000000010000
#   00000000001000000011000000000000
#   00000000000010000000000000001001
#   XX------XX------XX------XX------
#
# Conjecture (high confidence): 6x4 L-field is expanded into a 32-bit word by padding each
# 6-bit field part up to a 8-bit word part by adding zeroes as MSB. All words appear to separate
# into 4 8-bit chunks.
#
# JED address to word address mapping
# -----------------------------------
#
# Each JED block is 432-bit, i.e. the padding bits are not encoded. This makes mapping from
# JED blocks to bitstream words nontrivial. The mapping algorithm from field-aligned JED fuse
# addresses to word addresses is as follows:
#
#   block_num = jed_address // 432
#   block_bit = jed_address % 432
#   word_addr = block_num * 15
#   if block_bit < 9 * 32:
#     word_addr += block_bit // 32
#   else:
#     word_addr += 9 + (block_bit - 9 * 32) // 24
#
# Bitstream address structure
# ---------------------------
#
# While FVFYI reads out words (apparently) exactly as they are laid out in bitstream, FVFY and
# FPGM have a more complicated addressing scheme. This is likely because the blocks are not
# made from a power-of-2 amount of words, and the developers of the CPLD wanted an addressing
# scheme that has a direct relationship between address lines and words.
#
# Based on ISE SVF files, it is clear that each block (15 words) occupies 32 sequential addresses.
# The words inside a block are mapped to addresses as follows:
#     0->N+ 0   1->N+ 1   2->N+ 2   3->N+ 3   4->N+ 4
#     5->N+ 8   6->N+ 9   7->N+10   8->N+11   9->N+12
#    10->N+16  11->N+17  12->N+18  13->N+19  14->N+20
#
# Conjecture (high confidence): each block occupies 32 words of address space, split into 4
# groups of 8 words of address space. Of each group, only 5 first words are allocated.
#
# Additionally, based on SVF files and readout, it appears that the first 3 groups are written
# during flashing, but the 4th group is hardcoded, and points to some sort of identification
# or synchronization registers, laid out as follows:
#    SA->N+24  SB->N+25  SZ->N+26  SZ->N+27  SZ->N+27
# where:
#    SA=11001001110010011100100111001001 0x93939393
#    SB=01001010010010100000000101001010 0x52528052
#    SZ=00000000000000000000000000000000
#
# The SVF files do not verify these words.
#
# Revisiting earlier conjecture, it looks like with FVFYI command, the internal address counter
# starts at offset 24 and reads the 5-word 4th group as well. However, after that, it continues
# to read an entire 15-word empty block (i.e., FVFYI effectively starts with a 20-word padding)
# and then continues to read the first three groups of every block in sequence.
#
# Based on functional observation, FVFY sets the address counter used by FVFYI, and this can
# be used to avoid reading any of the "padding" with FVFYI.
#
# Word address to FPGM/FVFY address mapping
# -----------------------------------------
#
# The mapping algorithm from word address to FPGM/FVFY (device) address is as follows:
#
#   block_num = word_addr // 15
#   block_off = word_addr % 15
#   dev_addr  = 32 * block_num + 8 * (block_off // 5) + block_off % 5
#
# Bitstream encoding of USERCODE
# ------------------------------
#
# Comparing JED files for devices with USERCODE=0x30303030 (---) versus USERCODE=0xaaaaaaaa (+++):
#
#   +L0002592 00000010 00000000 00000000 00000000*
#   +L0002624 00000010 00000000 00000000 00000000*
#   +L0002656 00000010 00000000 00000000 00000000*
#   +L0002688 00000010 00000000 00000000 00000000*
#   +L0002720 00000010 00000000 00000000 00000000*
#   +L0002752 00000010 00000000 00000000 00000000*
#   +L0002784 00000010 00000000 00000000 00000000*
#   +L0002816 00000010 00000000 00000000 00000000*
#   +L0003024 00000010 00000000 00000000 00000000*
#   +L0003056 00000010 00000000 00000000 00000000*
#   +L0003088 00000010 00000000 00000000 00000000*
#   +L0003120 00000010 00000000 00000000 00000000*
#   +L0003152 00000010 00000000 00000000 00000000*
#   +L0003184 00000010 00000000 00000000 00000000*
#   +L0003216 00000010 00000000 00000000 00000000*
#   +L0003248 00000010 00000000 00000000 00000000*
#   -L0002592 00000000 00000000 00000000 00000000*
#   -L0002624 00000011 00000000 00000000 00000000*
#   -L0002656 00000000 00000000 00000000 00000000*
#   -L0002688 00000000 00000000 00000000 00000000*
#   -L0002720 00000000 00000000 00000000 00000000*
#   -L0002752 00000011 00000000 00000000 00000000*
#   -L0002784 00000000 00000000 00000000 00000000*
#   -L0002816 00000000 00000000 00000000 00000000*
#   -L0003024 00000000 00000000 00000000 00000000*
#   -L0003056 00000011 00000000 00000000 00000000*
#   -L0003088 00000000 00000000 00000000 00000000*
#   -L0003120 00000000 00000000 00000000 00000000*
#   -L0003152 00000000 00000000 00000000 00000000*
#   -L0003184 00000011 00000000 00000000 00000000*
#   -L0003216 00000000 00000000 00000000 00000000*
#   -L0003248 00000000 00000000 00000000 00000000*
#
# It can be seen that USERCODE is written in the following device words:
#    90,  91,  92,  93,  94,  95,  96,  97,
#   105, 106, 107, 108, 109, 110, 111, 112
#
# It is split into half-nibbles, and written MSB first into bits 6 and 7 of the device words.
#
# Other notes
# -----------
#
# The programming process is not self-timed and requires a clock to be provided in Run-Test/Idle
# state; otherwise programming will fail. Thus, this applet assumes that the number of clock
# cycles, and not the programming time, per se, is critical. This might not be true.
#
# The FPGMI instruction works similarly to FVFYI, but it looks like the counter is only set
# by FPGM in a way that it is reused by FPGMI once FPGM DR is updated once with the strobe bit
# set.

import struct
import logging
import argparse
import re
from bitarray import bitarray

from . import JTAGApplet
from .. import *
from ...arch.jtag import *
from ...arch.xilinx.xc9500 import *
from ...database.xilinx.xc9500 import *


BLOCK_FUSES = 432
BLOCK_WORDS = 15
GROUP_WORDS = 5


def jed_to_device_address(jed_address):
    block_num = jed_address // BLOCK_FUSES
    block_bit = jed_address  % BLOCK_FUSES
    word_address = block_num * 15
    if block_bit < 9 * 32:
        word_address += block_bit // 32
    else:
        word_address += 9 + (block_bit - 9 * 32) // 24
    return word_address


def bitstream_to_device_address(word_address):
    block_num = word_address // BLOCK_WORDS
    block_off = word_address  % BLOCK_WORDS
    return 32 * block_num + 8 * (block_off // GROUP_WORDS) + block_off % GROUP_WORDS


class JTAGXC9500Interface:
    def __init__(self, interface, logger, frequency):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._frequency = frequency

    def _log(self, message, *args):
        self._logger.log(self._level, "XC9500: " + message, *args)

    async def identify(self):
        await self.lower.write_ir(IR_IDCODE)
        idcode_bits = await self.lower.read_dr(32)
        idcode = DR_IDCODE.from_bitarray(idcode_bits)
        self._log("read IDCODE mfg_id=%03x part_id=%04x",
                  idcode.mfg_id, idcode.part_id)
        device = devices[idcode.mfg_id, idcode.part_id]
        return idcode, device

    async def read_usercode(self):
        await self.lower.write_ir(IR_USERCODE)
        usercode_bits = await self.lower.read_dr(32)
        self._log("read USERCODE %s", usercode_bits.to01())
        return usercode_bits.tobytes()

    async def programming_enable(self):
        self._log("programming enable")
        await self.lower.write_ir(IR_ISPEN)

    async def programming_disable(self):
        self._log("programming disable")
        await self.lower.write_ir(IR_ISPEX)

    async def _fvfy(self, address, count):
        await self.lower.write_ir(IR_FVFY)

        dev_address = bitstream_to_device_address(address)
        self._log("read address=%03x", dev_address)
        isconf = DR_ISCONFIGURATION(valid=1, strobe=1, address=dev_address)
        await self.lower.write_dr(isconf.to_bitarray()[:50])

        words = []
        for offset in range(count):
            dev_address = bitstream_to_device_address(address + offset + 1)
            isconf = DR_ISCONFIGURATION(valid=1, strobe=1, address=dev_address)
            isconf_bits = await self.lower.exchange_dr(isconf.to_bitarray()[:50])
            isconf = DR_ISCONFIGURATION.from_bitarray(isconf_bits)
            self._log("read address=%03x prev-data=%s",
                      dev_address, "{:032b}".format(isconf.data))
            words.append(isconf.data)

        return words

    async def _fvfyi(self, count):
        await self.lower.write_ir(IR_FVFYI)

        words = []
        index = 0
        while index < count:
            isdata_bits = await self.lower.read_dr(34)
            isdata = DR_ISDATA.from_bitarray(isdata_bits)
            if isdata.valid:
                self._log("read autoinc data=%s", "{:032b}".format(isdata.data))
                words.append(isdata.data)
                index += 1
            else:
                self._log("read autoinc invalid")

        return words

    async def read(self, address, count, fast=True):
        if fast:
            # Use FVFY just to set the address counter.
            await self._fvfy(address, 0)
            # Use FVFYI for much faster reads.
            return await self._fvfyi(count)
        else:
            # Use FVFY for all reads.
            return await self._fvfy(address, count)

    async def bulk_erase(self):
        self._log("bulk erase")
        await self.lower.write_ir(IR_FBULK)
        isaddr = DR_ISADDRESS(valid=1, strobe=1, address=0xffff)
        await self.lower.write_dr(isaddr.to_bitarray()[:18])

        await self.lower.run_test_idle(200_000)

        isaddr_bits = await self.lower.read_dr(18)
        isaddr = DR_ISADDRESS.from_bitarray(isaddr_bits)
        if not (isaddr.valid and not isaddr.strobe):
            raise GlasgowAppletError("bulk erase failed %s" % isaddr.bits_repr())

    async def _fpgm(self, address, words):
        await self.lower.write_ir(IR_FPGM)

        for offset, word in enumerate(words):
            dev_address = bitstream_to_device_address(address + offset)
            self._log("program address=%03x data=%s",
                      dev_address, "{:032b}".format(word))
            strobe = (offset % BLOCK_WORDS == BLOCK_WORDS - 1)
            isconf = DR_ISCONFIGURATION(valid=1, strobe=strobe, address=dev_address, data=word)
            await self.lower.write_dr(isconf.to_bitarray()[:50])

            if strobe:
                await self.lower.run_test_idle(20_000)

                isconf = DR_ISCONFIGURATION(address=dev_address)
                isconf_bits = await self.lower.exchange_dr(isconf.to_bitarray()[:50])
                isconf = DR_ISCONFIGURATION.from_bitarray(isconf_bits)
                if not (isconf.valid and not isconf.strobe):
                    self._logger.warn("program word %03x failed %s"
                                      % (offset, isconf.bits_repr()))

        if not words:
            dev_address = bitstream_to_device_address(address)
            isconf = DR_ISCONFIGURATION(valid=1, address=dev_address)
            await self.lower.write_dr(isconf.to_bitarray()[:50])

    async def _fpgmi(self, words):
        await self.lower.write_ir(IR_FPGMI)

        for offset, word in enumerate(words):
            self._log("program autoinc data=%s",
                      "{:032b}".format(word))
            strobe = (offset % BLOCK_WORDS == BLOCK_WORDS - 1)
            isdata = DR_ISDATA(valid=1, strobe=strobe, data=word)
            await self.lower.write_dr(isdata.to_bitarray()[:34])

            if strobe:
                await self.lower.run_test_idle(20_000)

                isdata = DR_ISDATA()
                isdata_bits = await self.lower.exchange_dr(isdata.to_bitarray()[:34])
                isdata = DR_ISDATA.from_bitarray(isdata_bits)
                if not (isdata.valid and not isdata.strobe):
                    self._logger.warn("program autoinc word %03x failed %s"
                                      % (offset, isdata.bits_repr()))

    async def program(self, address, words, fast=True):
        assert address % BLOCK_WORDS == 0 and len(words) % BLOCK_WORDS == 0

        if fast:
            # Use FPGM to program first block and set the address counter.
            await self._fpgm(0, words[:BLOCK_WORDS])
            # Use FPGMI for much faster following writes.
            return await self._fpgmi(words[BLOCK_WORDS:])
        else:
            # Use FPGM for all writes.
            return await self._fpgm(address, words)


class JTAGXC9500Applet(JTAGApplet, name="jtag-xc9500"):
    logger = logging.getLogger(__name__)
    help = "program Xilinx XC9500 CPLDs via JTAG"
    description = """
    Program, verify, and read out Xilinx XC9500 series CPLD bitstreams via the JTAG interface.

    It is recommended to use TCK frequency between 100 and 250 kHz for programming.

    The "program word failed" messages during programming do not necessarily mean a failed
    programming attempt or a bad device. Always verify the programmed bitstream.

    The list of supported devices is:
{devices}

    The Glasgow .bit XC9500 bitstream format is a flat, unstructured sequence of 32-bit words
    comprising the bitstream, written in little endian binary. It is substantially different
    from both .jed and .svf bitstream formats, but matches the internal device programming
    architecture.
    """.format(
        devices="\n".join(map(lambda x: "        * {.name}\n".format(x), devices.values()))
    )

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)

        parser.add_argument(
            "--tap-index", metavar="INDEX", type=int, default=0,
            help="select TAP #INDEX for communication (default: %(default)s)")

    async def run(self, device, args):
        jtag_iface = await super().run(device, args)
        await jtag_iface.pulse_trst()

        tap_iface = await jtag_iface.select_tap(args.tap_index)
        if not tap_iface:
            raise GlasgowAppletError("cannot select TAP #%d" % args.tap_index)

        return JTAGXC9500Interface(tap_iface, self.logger, args.frequency * 1000)

    @classmethod
    def add_interact_arguments(cls, parser):
        parser.add_argument(
            "--slow", default=False, action="store_true",
            help="use slower but potentially more robust algorithms, where applicable")

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")

        p_read_bit = p_operation.add_parser(
            "read-bit", help="read bitstream from the device and save it to a .bit file")
        p_read_bit.add_argument(
            "bit_file", metavar="BIT-FILE", type=argparse.FileType("wb"),
            help="bitstream file to write")

        p_program_bit = p_operation.add_parser(
            "program-bit", help="read bitstream from a .bit file and program it to the device")
        p_program_bit.add_argument(
            "bit_file", metavar="BIT-FILE", type=argparse.FileType("rb"),
            help="bitstream file to read")

        p_verify_bit = p_operation.add_parser(
            "verify-bit", help="read bitstream from a .bit file and verify it against the device")
        p_verify_bit.add_argument(
            "bit_file", metavar="BIT-FILE", type=argparse.FileType("rb"),
            help="bitstream file to read")

        p_erase = p_operation.add_parser(
            "erase", help="erase bitstream from the device")

    async def interact(self, device, args, xc9500_iface):
        idcode, device = await xc9500_iface.identify()
        if device is None:
            raise GlasgowAppletError("cannot operate on unknown device IDCODE=%08x"
                                     % idcode.to_int())
        self.logger.info("IDCODE=%08x device=%s rev=%d",
                         idcode.to_int(), device.name, idcode.version)

        usercode = await xc9500_iface.read_usercode()
        self.logger.info("USERCODE=%s (%s)",
                         usercode.hex(),
                         re.sub(rb"[^\x20-\x7e]", b"?", usercode).decode("ascii"))

        try:
            if args.operation == "read-bit":
                await xc9500_iface.programming_enable()
                for word in await xc9500_iface.read(0, device.bitstream_words,
                                                    fast=not args.slow):
                    args.bit_file.write(struct.pack("<L", word))

            if args.operation in ("program-bit", "verify-bit"):
                words = []
                while True:
                    data = args.bit_file.read(4)
                    if data == b"": break
                    words.append(*struct.unpack("<L", data))

                if len(words) != device.bitstream_words:
                    raise GlasgowAppletError("incorrect .bit file size (%d words) for device %s"
                                             % (len(words), device.name))

            if args.operation == "program-bit":
                await xc9500_iface.programming_enable()
                await xc9500_iface.program(0, words,
                                           fast=not args.slow)

            if args.operation == "verify-bit":
                await xc9500_iface.programming_enable()
                device_words = await xc9500_iface.read(0, device.bitstream_words,
                                                       fast=not args.slow)
                for offset, (device_word, gold_word) in enumerate(zip(device_words, words)):
                    if device_word != gold_word:
                        raise GlasgowAppletError("bitstream verification failed at word %03x"
                                                 % offset)

            if args.operation == "erase":
                await xc9500_iface.programming_enable()
                await xc9500_iface.bulk_erase()

        finally:
            await xc9500_iface.programming_disable()

# -------------------------------------------------------------------------------------------------

class JTAGXC9500AppletTool(GlasgowAppletTool, applet=JTAGXC9500Applet):
    help = "manipulate Xilinx XC9500 CPLD bitstreams"
    description = """
    See `run jtag-xc9500 --help` for details.
    """

    @classmethod
    def add_arguments(cls, parser):
        def idcode(arg):
            idcode = DR_IDCODE.from_int(int(arg, 16))
            device = devices[idcode.mfg_id, idcode.part_id]
            if device is None:
                raise argparse.ArgumentTypeError("unknown IDCODE")
            return device

        parser.add_argument(
            "-d", "--device", metavar="IDCODE", type=idcode, required=True,
            help="select device with given JTAG IDCODE")

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")

        p_read_bit_usercode = p_operation.add_parser(
            "read-bit-usercode", help="read USERCODE from a .bit file")
        p_read_bit_usercode.add_argument(
            "bit_file", metavar="BIT-FILE", type=argparse.FileType("rb"),
            help="bitstream file to read")

    async def run(self, args):
        if args.operation == "read-bit-usercode":
            words = []
            while True:
                data = args.bit_file.read(4)
                if data == b"": break
                words.append(*struct.unpack("<L", data))

            if len(words) != args.device.bitstream_words:
                raise GlasgowAppletError("incorrect .bit file size (%d words) for device %s"
                                         % (len(words), args.device.name))

            usercode_words = [
                words[index] for index in range(args.device.usercode_low,
                                                args.device.usercode_low  + 8)
            ] + [
                words[index] for index in range(args.device.usercode_high,
                                                args.device.usercode_high + 8)
            ]
            usercode = 0
            for usercode_word in usercode_words:
                usercode = (usercode << 2) | ((usercode_word >> 6) & 0b11)
            usercode = struct.pack("<L", usercode)
            self.logger.info("USERCODE=%s (%s)",
                             usercode.hex(),
                             re.sub(rb"[^\x20-\x7e]", b"?", usercode).decode("ascii"))
