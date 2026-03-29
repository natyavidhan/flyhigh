import serial
import struct
import time

PORT = "COM6"
BAUD = 115200

ser = serial.Serial(PORT, BAUD, timeout=1)

def read_frame(ser):
    while True:
        b1 = ser.read(1)
        if b1 and b1[0] == 0x55:
            b2 = ser.read(1)
            if b2 and b2[0] == 0xFC:
                data = ser.read(14)  # 14 bytes, not 12
                if len(data) == 14:
                    return data

stats = {i: {'min': 99999, 'max': 0} for i in range(6)}

print("Move ALL sticks and knobs to full extremes for 10 seconds...\n")

start = time.time()
while time.time() - start < 10:
    data = read_frame(ser)
    raw = struct.unpack_from('>6H', data)  # > = big-endian
    for i, val in enumerate(raw):
        stats[i]['min'] = min(stats[i]['min'], val)
        stats[i]['max'] = max(stats[i]['max'], val)

print("\nYour actual ranges:")
for i, s in stats.items():
    mid = (s['min'] + s['max']) // 2
    print(f"  CH{i+1}: min={s['min']}  mid≈{mid}  max={s['max']}")