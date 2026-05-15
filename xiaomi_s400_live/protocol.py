"""Mi Home BLE protocol constants for Xiaomi Body Composition Scale S400."""

# Auth service (0xFE95) characteristic UUIDs
UPNP  = "00000010-0000-1000-8000-00805f9b34fb"  # client → device commands
AVDTP = "00000019-0000-1000-8000-00805f9b34fb"  # bidirectional auth data
AVCTP = "00000017-0000-1000-8000-00805f9b34fb"

# Encrypted command channel (post-login)
VEND1A = "0000001a-0000-1000-8000-00805f9b34fb"  # app → device encrypted
CMTP   = "0000001b-0000-1000-8000-00805f9b34fb"  # device → app encrypted
VEND1C = "0000001c-0000-1000-8000-00805f9b34fb"

# MiBeacon advertisement service (used by passive scan path, not GATT)
MIBEACON_SERVICE_UUID = "0000fe95-0000-1000-8000-00805f9b34fb"

# Commands written to UPNP (4-byte little-endian opcode)
CMD_GET_INFO = bytes.fromhex("a2000000")
CMD_SET_KEY  = bytes.fromhex("15000000")
CMD_LOGIN    = bytes.fromhex("24000000")
CMD_AUTH     = bytes.fromhex("13000000")

# Framing headers written to AVDTP (3B fixed + 1B type + 2B frame_count_LE)
CMD_SEND_DATA = bytes.fromhex("000000030400")
CMD_SEND_KEY  = bytes.fromhex("0000000b0100")
CMD_SEND_INFO = bytes.fromhex("0000000a0200")
CMD_SEND_DID  = bytes.fromhex("000000000200")

# Receiver acks
RCV_RDY = bytes.fromhex("00000101")
RCV_OK  = bytes.fromhex("00000100")

# Auth result codes (on UPNP)
CFM_REGISTER_OK  = bytes.fromhex("11000000")
CFM_REGISTER_ERR = bytes.fromhex("12000000")
CFM_LOGIN_OK     = bytes.fromhex("21000000")
CFM_LOGIN_ERR    = bytes.fromhex("23000000")
AUTH_ERRORS = {
    bytes.fromhex("e0000000"),
    bytes.fromhex("e1000000"),
    bytes.fromhex("e2000000"),
    bytes.fromhex("e3000000"),
}
