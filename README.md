# pyusbip

`pyusbip` is a userspace USBIP server implementation based on `python-libusb1`. (In USBIP, the 'server' has the physical USB device attached, and the 'client' has only a network cable attached; i.e., you run this if you have a USB device attached to your local machine that you'd like to be able to use on a different computer.)

It has been tested (for small values of "tested") on Mac OS X; it is, at least, sufficient to forward a Lattice MachXO3 eval kit to the Lattice programmer software.

## Usage instructions

Following is a rough recipe for getting started with forwarding a USB device using `pyusbip`.

* Make sure that you have `python-libusb1` installed: `pip install libusb1`.
* As necessary on your platform, give yourself permission to access the USB device.
* Launch pyusbip: `python3 pyusbip.py`
* Forward the port to another machine: `ssh you@target_machine -C -R 3240:127.0.0.1:3240`
* Find the device you want: `sudo usbip list -r 127.0.0.1`
* Attach the device you want: `sudo usbip attach -r 127.0.0.1 -b 20-4`
* Enjoy!

## Limitations

`pyusbip` has many limitations.  Much of the protocol is unimplemented; `pyusbip` simply disconnects a device and drops a connection if it trips on that.  In some cases, protocol violations in USBIP can cause the Linux kernel's entire USB stack to crash (!); for instance, if `pyusbip` gets stuck transmitting half of a response URB, you may need to reboot the remote end before it'll come back to life.  Following is a list of known limitations in `pyusbip`:

* `pyusbip` gives up on a device if it can't claim all interfaces, rather than failing URBs with `-EPERM` or some such.  (This is a problem when exporting, say, a ST-Link board that also has a mass storage device, from OS X.)
* `pyusbip`'s control traffic is synchronous.
* `pyusbip` does not keep track of what type of endpoint it's talking to, and as such, always sends bulk requests, even to interrupt or isochronous endpoints.
* `pyusbip` does not implement isochronous endpoints at all.
* Error handling usually results in forcing a device disconnect, rather than doing anything reasonable.
* `UNLINK` requests may send a spurious URB reply, which could confuse some clients.
* Comments are ... sparse.
* Code architecture is suspicious.

## Contact

`pyusbip` is unsupported.  Please use [the GitHub repository](https://github.com/jwise/pyusbip) to submit patches.  If you need to, you can [contact the author](https://joshuawise.com/contact).
