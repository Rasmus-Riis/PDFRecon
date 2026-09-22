import time
from datetime import datetime

date_str = "20231024123456"

start = time.perf_counter()
for _ in range(100000):
    dt_obj = datetime.strptime(date_str, "%Y%m%d%H%M%S")
print("strptime:", time.perf_counter() - start)

start = time.perf_counter()
for _ in range(100000):
    dt_obj = datetime(
        int(date_str[0:4]),
        int(date_str[4:6]),
        int(date_str[6:8]),
        int(date_str[8:10]),
        int(date_str[10:12]),
        int(date_str[12:14])
    )
print("direct:", time.perf_counter() - start)
