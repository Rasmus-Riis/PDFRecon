from datetime import datetime

d1_str = "2023-10-24T12:34:56"
fmt = "%Y-%m-%dT%H:%M:%S"
print(datetime.strptime(d1_str[:19], fmt) == datetime.fromisoformat(d1_str[:19]))

date_str = "20231024123456"
print(datetime.strptime(date_str, "%Y%m%d%H%M%S") == datetime(
    int(date_str[0:4]), int(date_str[4:6]), int(date_str[6:8]),
    int(date_str[8:10]), int(date_str[10:12]), int(date_str[12:14])
))
