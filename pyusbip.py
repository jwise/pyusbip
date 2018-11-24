#!/usr/bin/env python3

import asyncio
import usb1
import struct
import traceback

USBIP_HOST = '127.0.0.1'
USBIP_PORT = 3240

USBIP_REQUEST   = 0x8000
USBIP_REPLY     = 0x0000

USBIP_OP_UNSPEC   = 0x00
USBIP_OP_DEVINFO  = 0x02
USBIP_OP_IMPORT   = 0x03
USBIP_OP_EXPORT   = 0x06
USBIP_OP_UNEXPORT = 0x07
USBIP_OP_DEVLIST  = 0x05

USBIP_CMD_SUBMIT = 0x0001
USBIP_CMD_UNLINK = 0x0002
USBIP_RET_SUBMIT = 0x0003
USBIP_RET_UNLINK = 0x0004
USBIP_RESET_DEV  = 0xFFFF

USBIP_DIR_OUT    = 0
USBIP_DIR_IN     = 1

USBIP_ST_OK      = 0x00
USBIP_ST_NA      = 0x01

USBIP_BUS_ID_SIZE = 32
USBIP_DEV_PATH_MAX = 256

USBIP_VERSION = 0x0111

USBIP_SPEED_UNKNOWN = 0
USBIP_SPEED_LOW = 1
USBIP_SPEED_FULL = 2
USBIP_SPEED_HIGH = 3
USBIP_SPEED_VARIABLE = 4

USB_RECIP_DEVICE          = 0x00
USB_RECIP_INTERFACE       = 0x01
USB_REQ_SET_ADDRESS       = 0x05
USB_REQ_SET_CONFIGURATION = 0x09
USB_REQ_SET_INTERFACE     = 0x0B

USB_EPIPE = 32

usbctx = usb1.USBContext()
usbctx.open()

class USBIPUnimplementedException(Exception):
    def __init__(self, message):
        self.message = message

class USBIPProtocolErrorException(Exception):
    def __init__(self, message):
        self.message = message

class USBIPDevice:
    def __init__(self, devid, hnd):
        self.devid = devid
        self.hnd = hnd

class USBIPConnection:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        self.devices = {}
        self.urbs = {}
        
    def say(self, str):
        addr = self.writer.get_extra_info('peername')
        print('{}: {}'.format(addr, str))
        
    def pack_device_desc(self, dev, interfaces = True):
        """Takes a usb1 device and packs it into a struct usb_device (and
        optionally, struct usb_interfaces)."""
    
        path = "pyusbip/{}/{}".format(dev.getBusNumber(), dev.getDeviceAddress())
        busid = "{}-{}".format(dev.getBusNumber(), dev.getDeviceAddress())
        busnum = dev.getBusNumber()
        devnum = dev.getDeviceAddress()
        speed = {
            usb1.SPEED_UNKNOWN: USBIP_SPEED_UNKNOWN,
            usb1.SPEED_LOW: USBIP_SPEED_LOW,
            usb1.SPEED_FULL: USBIP_SPEED_FULL,
            usb1.SPEED_HIGH: USBIP_SPEED_HIGH,
            usb1.SPEED_SUPER: USBIP_SPEED_HIGH,
        }[dev.getDeviceSpeed()]
        
        idVendor = dev.getVendorID()
        idProduct = dev.getProductID()
        bcdDevice = dev.getbcdDevice()
        
        bDeviceClass = dev.getDeviceClass()
        bDeviceSubClass = dev.getDeviceSubClass()
        bDeviceProtocol = dev.getDeviceProtocol()
        configs = list(dev.iterConfigurations())
        try:
            hnd = dev.open()
            bConfigurationValue = hnd.getConfiguration()
            hnd.close()
        except Exception:
            bConfigurationValue = configs[0].getConfigurationValue()
        bNumConfigurations = dev.getNumConfigurations()
        
        # Sigh, find it.
        config = configs[0]
        for _config in configs:
            if _config.getConfigurationValue() == bConfigurationValue:
                config = _config
                break
        bNumInterfaces = config.getNumInterfaces()
        
        data = struct.pack(">256s32sIIIHHHBBBBBB",
            path.encode(), busid.encode(),
            busnum, devnum, speed,
            idVendor, idProduct, bcdDevice,
            bDeviceClass, bDeviceSubClass, bDeviceProtocol, bConfigurationValue, bNumConfigurations, bNumInterfaces)
        
        if interfaces:
            for ifc in config.iterInterfaces():
                set = list(ifc)[0]
                data += struct.pack(">BBBB", set.getClass(), set.getSubClass(), set.getProtocol(), 0)
    
        return data
    
    def handle_op_devlist(self):
        devlist = usbctx.getDeviceList()
        
        resp = struct.pack(">HHII", USBIP_VERSION, USBIP_OP_DEVLIST | USBIP_REPLY, USBIP_ST_OK, len(devlist))
        for dev in devlist:
            resp += self.pack_device_desc(dev)
        
        self.writer.write(resp)
    
    def handle_op_import(self, busid):
        # We kind of do this the hard way -- rather than looking up by bus
        # id / device address, we instead just compare the string.  Life is
        # too short to extend python-libusb1.
        devlist = usbctx.getDeviceList()
        for dev in devlist:
            dev_busid = "{}-{}".format(dev.getBusNumber(), dev.getDeviceAddress())
            if busid == dev_busid:
                hnd = dev.open()
                self.say('opened device {}'.format(busid))
                devid = dev.getBusNumber() << 16 | dev.getDeviceAddress()
                self.devices[devid] = USBIPDevice(devid, hnd)
                resp = struct.pack(">HHI", USBIP_VERSION, USBIP_OP_IMPORT | USBIP_REPLY, USBIP_ST_OK)
                resp += self.pack_device_desc(dev, interfaces = False)
                self.writer.write(resp)
                return
        
        self.say('device not found')
        resp = struct.pack(">HHI", USBIP_VERSION, USBIP_OP_IMPORT | USBIP_REPLY, USBIP_ST_NA)
        self.writer.write(resp)
    
    async def handle_urb_submit(self, seqnum, dev, direction, ep):
        op_submit = ">Iiiii8s"
        data = await self.reader.readexactly(struct.calcsize(op_submit))
        (transfer_flags, buflen, start_frame, number_of_packets, interval, setup) = struct.unpack(op_submit, data)
        
        if number_of_packets != 0:
            raise USBIPUnimplementedException("ISO number_of_packets {}".format(number_of_packets))
        
        if direction == USBIP_DIR_OUT:
            buf = await self.reader.readexactly(buflen)
        
        if ep == 0:
            # EP0 control traffic; unpack the control request
            (bRequestType, bRequest, wValue, wIndex, wLength) = struct.unpack("<BBHHH", setup)
            if wLength != buflen:
                raise USBIPProtocolErrorException("wLength {} neq buflen {}".format(wlength, buflen))
            self.say("EP0 requesttype {}, request {}".format(bRequestType, bRequest))
            
            fakeit = False
            
            if bRequestType == USB_RECIP_DEVICE and bRequest == USB_REQ_SET_ADDRESS:
                raise USBIPUnimplementedException("USB_REQ_SET_ADDRESS")
            elif bRequestType == USB_RECIP_DEVICE and bRequest == USB_REQ_SET_CONFIGURATION:
                self.say('set configuration: {}'.format(wValue))
                dev.hnd.setConfiguration(wValue)
                fakeit = True
            elif bRequestType == USB_RECIP_INTERFACE and bRequest == USB_REQ_SET_INTERFACE:
                self.say('set interface alt setting: {} -> {}'.format(wIndex, wValue))
                dev.hnd.claimInterface(wIndex)
                dev.hnd.setInterfaceAltSetting(wIndex, wValue)
                fakeit = True
            
            # cheese it, and do it synchronously for right now, why not ...
            try:
                if direction == USBIP_DIR_IN:
                    data = dev.hnd.controlRead(bRequestType, bRequest, wValue, wIndex, wLength)
                    resp = struct.pack(">IIIIIiiiii8s",
                        USBIP_RET_SUBMIT, seqnum,
                        0, 0, 0,
                        #dev.devid, direction, ep,
                        0, len(data), 0, 0, 0,
                        b'')
                    resp += data
                    self.say("wrote response with {}/{} bytes".format(len(data), wLength))
                    self.writer.write(resp)
                else:
                    if fakeit:
                        wlen = 0
                    else:
                        wlen = dev.hnd.controlWrite(bRequestType, bRequest, wValue, wIndex, buf)
                    resp = struct.pack(">IIIIIiiiii8s",
                        USBIP_RET_SUBMIT, seqnum,
                        0, 0, 0,
                        0, wlen, 0, 0, 0,
                        b'')
                    self.say("wrote {}/{} bytes".format(wlen, wLength))
                    self.writer.write(resp)
            except usb1.USBErrorPipe:
                resp = struct.pack(">IIIIIiiiii8s",
                    USBIP_RET_SUBMIT, seqnum,
                    0, 0, 0,
                    -USB_EPIPE, 0, 0, 0, 0,
                    b'')
                self.say('EPIPE')
                self.writer.write(resp)
        
        self.say("seq {:x}: ep {}, direction {}, {} bytes".format(seqnum, ep, direction, buflen))
    
    async def handle_packet(self):
        """
        Handle a USBIP packet.
        """
        
        # Try to read a header of some kind.  We can tell because if it's an
        # URB, the |op_common.version| is overlayed with the
        # |usbip_header_basic.command|, and so the |.version| is 0x0000;
        # otherwise, it's supposed to be 0x0106.
        
        try:
            data = await self.reader.readexactly(2)
        except asyncio.streams.IncompleteReadError:
            return False
            
        (version, ) = struct.unpack(">H", data)
        if version == 0x0000:
            # Note that we've already trimmed the version.
            op_common = ">HIIII";
            data = await self.reader.readexactly(struct.calcsize(op_common))
            (opcode, seqnum, devid, direction, ep) = struct.unpack(op_common, data)
            
            if devid not in self.devices:
                raise USBIPProtocolErrorException('devid unattached {:x}'.format(devid))
            dev = self.devices[devid]
            
            if opcode == USBIP_CMD_SUBMIT:
                await self.handle_urb_submit(seqnum, dev, direction, ep)
            elif opcode == USBIP_CMD_UNLINK:
                raise USBIPUnimplementedException("URB UNLINK")
            elif opcode == USBIP_RESET_DEV:
                raise USBIPUnimplementedException("URB_RESET_DEV")
            else:
                raise USBIPProtocolErrorException('bad USBIP URB {:x}'.format(opcode))
        elif (version & 0xff00) == 0x0100:
            # Note that we've already trimmed the version.
            op_common = ">HI"
            data = await self.reader.readexactly(struct.calcsize(op_common))
            (opcode, status) = struct.unpack(op_common, data)
            
            if opcode == USBIP_OP_UNSPEC | USBIP_REQUEST:
                self.writer.write(struct.pack(">HHI", version, USBIP_OP_UNSPEC | USBIP_REPLY, USBIP_ST_OK))
            elif opcode == USBIP_OP_DEVINFO | USBIP_REQUEST:
                data = await self.reader.readexactly(USBIP_BUS_ID_SIZE)
                raise USBIPUnimplementedException("DEVINFO")
                # writer.write(struct.pack(">HHI", version, USBIP_OP_DEVINFO | USBIP_REPLY, USBIP_ST_NA)
            elif opcode == USBIP_OP_DEVLIST | USBIP_REQUEST:
                self.say('DEVLIST')
                # XXX: in theory, op_devlist_request has a _reserved, but they don't seem to xmit it?
                # data = await self.reader.readexactly(4) # reserved
                self.handle_op_devlist()
            elif opcode == USBIP_OP_IMPORT | USBIP_REQUEST:
                data = (await self.reader.readexactly(USBIP_BUS_ID_SIZE)).decode().rstrip('\0')
                self.say('IMPORT {}'.format(data))
                self.handle_op_import(data)
            else:
                raise USBIPProtocolErrorException('bad USBIP op {:x}'.format(opcode))
        else:
            raise USBIPProtocolErrorException("unsupported USBIP version {:02x}".format(version))
        
        return True
        
    async def connection(self):
        self.say('connect')
        
        while True:
            try:
                success = await self.handle_packet()
                await self.writer.drain()
                if not success:
                    break
            except Exception as e:
                traceback.print_exc()
                self.say('force disconnect due to exception')
                break

        self.say('disconnect')
        for i in self.devices:
            self.devices[i].hnd.close()
            self.devices[i] = None
        await self.writer.drain()
        self.writer.close()
        
async def usbip_connection(reader, writer):
    conn = USBIPConnection(reader, writer)
    await conn.connection()

loop = asyncio.get_event_loop()
coro = asyncio.start_server(usbip_connection, USBIP_HOST, USBIP_PORT, loop = loop)
server = loop.run_until_complete(coro)

print('Serving on {}'.format(server.sockets[0].getsockname()))
try:
    loop.run_forever()
except KeyboardInterrupt:
    pass

print('Shutting down...')
server.close()
loop.run_until_complete(server.wait_closed())
loop.close()
