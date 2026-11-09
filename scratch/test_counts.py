import sys, os
sys.path.insert(0, os.getcwd())
from detector import count_vehicles
c1 = count_vehicles("static/samples/real_day_traffic.jpg", "north")[0]
print("real_day_traffic count:", c1)
c2 = count_vehicles("static/samples/sample_north.jpg", "north")[0]
print("sample_north count:", c2)
