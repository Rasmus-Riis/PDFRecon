import time
from datetime import datetime

d_str = "2023-10-24T12:34:56"
fmt = "%Y-%m-%dT%H:%M:%S"

start = time.perf_counter()
for _ in range(100000):
    dt1 = datetime.strptime(d_str, fmt)
print("strptime:", time.perf_counter() - start)

start = time.perf_counter()
for _ in range(100000):
    dt1 = datetime.fromisoformat(d_str)
print("fromisoformat:", time.perf_counter() - start)
