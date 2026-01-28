"""
This code sorts large cell groups that were not created through the recursive method.

Code is from v10order_group.py from Terra/Visualization folder
"""

#Travelling salesman implementation for connecting the wireframe points
#Uses closest point method

import math

class Point:
	def __init__(self, x_val, y_val):
		self.x_val = x_val
		self.y_val = y_val
		self.coords = [x_val, y_val]

		unsorted_point_list.append(self)

	def distance_from_point(self, other):	
		return(math.dist(self.coords, other.coords))

	def next_closest_point(self, chosen_list):

		current_closest_point_distance = [chosen_list[0], Point.distance_from_point(self, chosen_list[0])]

		for point in chosen_list:
			cur_distance = Point.distance_from_point(self, point)
			if  cur_distance < current_closest_point_distance[1]:
				current_closest_point_distance = [point, cur_distance]
		return(current_closest_point_distance[0])




#This function, if called, adds surrounding points. Makes the travelling salesman solution looser....
#Looseness on a scale from 1 to ....
#Only works if the outline is sorted BEFORE adjusted (rotated and translated)
def surrounding_coords(point, looseness):
	result = []
	x = point.x_val
	y = point.y_val

	if looseness >=1:
		result.append([x-1, y])
		result.append([x, y-1])
		result.append([x, y+1])
		result.append([x+1, y])
	
	if looseness >=2:
		result.append([x-1, y-1])
		result.append([x-1, y+1])
		result.append([x+1, y-1])
		result.append([x+1, y+1])
	
	if looseness >=3:
		result.append([x-2, y])
		result.append([x, y-2])
		result.append([x, y+2])
		result.append([x+2, y])
	return(result)

def coords_to_points(coords, lst):
	result = []
	for point in lst:
		if [point.x_val, point.y_val] in coords:
			result.append(point)
	return(result)

def evaluate_route(route):
	distance_traveled = 0
	for i in range(len(route) - 1):
		distance_traveled += Point.distance_from_point(route[i], route[i+1])
	return(distance_traveled)


def strategy_closest_point():
	global ordered_list
	ordered_list = [unsorted_point_list[0]]
	remaining_points = unsorted_point_list.copy()[1:len(unsorted_point_list)]
	
	cur_index = 0
	while (len(remaining_points) >0):
		add_list = []
		delete_list = []
		cur_point = ordered_list[cur_index]

		next_point = Point.next_closest_point(cur_point, remaining_points)
		add_list.append(next_point)
		delete_list.append(next_point)

		surroundings = surrounding_coords(next_point, 3)
		sur_ps = coords_to_points(surroundings, remaining_points)
		#add_list+=sur_ps
		delete_list+=sur_ps

		for p in add_list:
			ordered_list.append(p)
		
		for p in delete_list:
			remaining_points.remove(p)

		cur_index+=1
		
	print("Route Length: ", evaluate_route(ordered_list))


def sort_group(group):
	global unsorted_point_list
	global ordered_list
	unsorted_point_list, ordered_list = [], []
	
	for coords in group:
		Point(coords[0], coords[1])
	
	result = []
	strategy_closest_point()
	for p in ordered_list:
		result.append([p.x_val, p.y_val])
	return(result)
	

