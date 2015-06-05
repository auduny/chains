# Physical Specifications:
# 1. Baud Rate:1200, 2400, 4800, 9600 (default), 19200, 38400, 57600
# 2. Data bits: 8
# 3. Parity: None
# 4. Stop Bit: 1
# 5. Flow Control: None

#  ________________________________________________________________________________
# | MsgSize | Control | Data [0] | Data [1] | Data [2] | ... | Data [N] | Checksum |
# |_________|_________|__________|__________|__________|_____|__________|__________|
#
# MsgSize:
# Header, ID, Category, Page, Function, Length


def checksum(bytearr):
    """  Takes an array of bytes and XOR's them  """
    cur = bytearr[0]
    for item in bytearr[1:]:
        cur = cur ^ item
    return cur


def prep_msg(cmd_arr):
    cmd_arr.insert(0, 0xA6) # Header
    #cmd_arr.insert(1, 0x01) # Monitor ID: 0x00 -> 0xFF
    cmd_arr.insert(1, 0x01) # Monitor ID: 0x00 -> 0xFF
    cmd_arr.insert(2, 0x00) # Category: Fixed @ 0x00
    cmd_arr.insert(3, 0x00) # Page: Fixed @ 0x00
    cmd_arr.insert(4, 0x00) # Function: Fixed @ 0x00
    cmd_arr.insert(5, 0) # length of array not including msgsize/header part
    cmd_arr.insert(6, 0x01) # Control: Fixed @ 0x01
    cmd_arr.insert(5, len(cmd_arr) - 5) # update length when done
    cmd_arr.append(checksum(cmd_arr))
    return cmd_arr


if __name__ == '__main__':
    import serial
    import sicp
    print sicp.CMD
    command = prep_msg(bytearray([0x18, 0x01]))
    for index, val in enumerate(command):
       print "byte %d : %s" % (index, hex(val))
    print command
    ser = serial.Serial(
        port='/dev/ttyUSB0',
        baudrate=9600,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        bytesize=serial.EIGHTBITS
    )
    ser.flushInput()
    ser.flushOutput()
    cmd_status = False
    while True:
        if cmd_status == False:
            ser.write(command)
            cmd_status = True
        data_raw = ser.read()
        print int(data_raw)
    ser.close()
    # data_raw = ser.readline()
    # print str(data_raw)
