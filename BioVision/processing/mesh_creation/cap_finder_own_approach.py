#Cap finder own approach
"""
New attempt at cap finder

Code inputs:
- xz_outlines: List of 2D numpy arrays representing the XZ plane outlines
- yz_outlines: List of 2D numpy arrays representing the YZ plane outlines

"""
try:
    from . import kochanek_bartels_spline_safe
except ImportError:  # Allow running as a script.
    import kochanek_bartels_spline_safe
tens = 0
cont = 0
bias = 0


##-------Arch helper functions and class-------##
arches = []

def create_arches(XZ_outlines, YZ_outlines, top_or_bottom):
    for outline in XZ_outlines:
        new_arch = Arch(arch=[], XZ_outline=outline, YZ_outline=None, top_or_bottom=top_or_bottom)
    for outline in YZ_outlines:
        new_arch = Arch(arch=[], XZ_outline=None, YZ_outline=outline, top_or_bottom=top_or_bottom)

def identify_arch(outline, top_or_bottom):
    for arch in arches:
        if arch.top_or_bottom == top_or_bottom and (arch.XZ_outline == outline or arch.YZ_outline == outline):
            return(arch)
    return(None)

class Arch:
    def __init__(self, arch, XZ_outline, YZ_outline, top_or_bottom):
        self.arch = arch
        self.XZ_outline = XZ_outline
        self.YZ_outline = YZ_outline
        self.top_or_bottom = top_or_bottom

        if XZ_outline is None:
            self.XZ_or_YZ = "YZ"
        elif YZ_outline is None:
            self.XZ_or_YZ = "XZ"
        
        arches.append(self)

        
    def order_arch(self):                           ##AALLLLLEEERTTT SHOULDNT ORDER BE SWITCHED??? e[0] then e[1]
        if self.XZ_or_YZ == "XZ":
            self.arch = sorted(self.arch, key=lambda e: e[0])
        elif self.XZ_or_YZ == "YZ":
            self.arch = sorted(self.arch, key=lambda e: e[1])
        if self.top_or_bottom == "bottom":
            self.arch.reverse()
    

    def add_to_outline(self):           #Returns the outline with the arch added
        if self.XZ_or_YZ == "XZ":
            working_outline = self.XZ_outline
        elif self.XZ_or_YZ == "YZ":
            working_outline = self.YZ_outline

        self.order_arch()
        res = []
        if self.top_or_bottom == "top":
            middle = len(working_outline) // 2
            res.extend(working_outline[:middle])
            res.extend(self.arch)
            res.extend(working_outline[middle:])
        
        if self.top_or_bottom == "bottom":
            res.extend(working_outline)
            res.extend(self.arch)
        return(res)
##------------------------------------##
    

##-----CapPoint functions and class-----##
def find_z(XZ_pts, YZ_pts, intersection, top_or_bottom):
    global tens, cont, bias
    
    XZ_pts = [[pt[0], pt[2]] for pt in XZ_pts]
    z1 = kochanek_bartels_spline_safe.v_for_u_nonuniform(target_u = intersection[0],
                                                            P0 = XZ_pts[0], P1 = XZ_pts[1], P2 = XZ_pts[2], P3 = XZ_pts[3],
                                                            tension = tens, continuity = cont, bias = bias)
    YZ_pts = [[pt[1], pt[2]] for pt in YZ_pts]
    z2 = kochanek_bartels_spline_safe.v_for_u_nonuniform(target_u = intersection[1],
                                                            P0 = YZ_pts[0], P1 = YZ_pts[1], P2 = YZ_pts[2], P3 = YZ_pts[3],
                                                            tension = tens, continuity = cont, bias = bias)
    if top_or_bottom == "top":
        z1 = max(z1)
        z2 = max(z2)
    elif top_or_bottom == "bottom":
        z1 = min(z1)
        z2 = min(z2)
    
    return(min(z1, z2)) #Average might be better.

class CapPoint:
    def __init__(self, XZ_line, YZ_line, top_or_bottom, intersection):
        self.XZ_pts = four_imp_points(XZ_line, top_or_bottom)
        self.YZ_pts = four_imp_points(YZ_line, top_or_bottom)
        self.top_or_bottom = top_or_bottom
        self.intersection = intersection
        self.z = find_z(self.XZ_pts, self.YZ_pts, intersection, top_or_bottom)
        self.pos = (intersection[0], intersection[1], self.z)
##------------------------------------##



def find_min_max_z(outlines, top_or_bottom):
    all_z = []
    for outline in outlines:
        all_z.extend([pt[2] for pt in outline])

    res = max(all_z)
    if top_or_bottom == "bottom":
        res = min(all_z)
    
    return(res)


def find_cap_outlines(outlines, cap_lvl):   #Do I need to add uncertainty?
    cap_outlines = []
    for outline in outlines:
        for pt in outline:
            if pt[2] == cap_lvl:
                cap_outlines.append(outline)
                break
    return cap_outlines


def four_imp_points(outline, top_or_bottom):
    if len(outline) %2 !=0:
        pass
        #print("Outline has an odd number of points, cannot find four important points")
    if top_or_bottom == "top":
        middle = len(outline) // 2
        return([outline[middle-2], outline[middle-1], outline[middle], outline[middle+1]])
    
    if top_or_bottom == "bottom":
        return([outline[-2], outline[-1], outline[0], outline[1]])


def find_intersection(XZ_line, YZ_line, top_or_bottom):
    XZ_two = four_imp_points(XZ_line, top_or_bottom)
    YZ_two = four_imp_points(YZ_line, top_or_bottom)
    XZ_two = [XZ_two[1], XZ_two[2]]
    YZ_two = [YZ_two[1], YZ_two[2]]

    # Horizontal segment: y is constant
    y = XZ_two[0][1]
    x1, x2 = XZ_two[0][0], XZ_two[1][0]
    
    # Vertical segment: x is constant
    x = YZ_two[0][0]
    y1, y2 = YZ_two[0][1], YZ_two[1][1]
    
    if min(x1, x2) <= x <= max(x1, x2) and min(y1, y2) <= y <= max(y1, y2):
        return [x, y]
    else:
        return False



##-------SCALING FUNCTIONS-------##
def find_limit(outlines, top_or_bottom, cap_lvl):
    z_wo_top = []
    for outline in outlines:
        z_wo_top.extend([pt[2] for pt in outline if pt[2] != cap_lvl])

    second_top = max(z_wo_top)
    if top_or_bottom == "bottom":
        second_top = min(z_wo_top)
    
    dist_btwn_slices = abs(second_top - cap_lvl)

    if top_or_bottom == "top":
        return(cap_lvl + dist_btwn_slices)
    return(cap_lvl - dist_btwn_slices)


def scale(cap_points, cap_lvl, scale_factor):
    for point in cap_points:
        point.z = (point.z - cap_lvl) * scale_factor + cap_lvl


def scale_cap_points(cap_points, cap_lvl, limit, top_or_bottom):
    max_z = cap_points[0].z
    min_z = cap_points[0].z
    for point in cap_points:
        if point.z > max_z:
            max_z = point.z
        if point.z < min_z:
            min_z = point.z
    
    if top_or_bottom == "top" and max_z > limit:
        scale_factor = abs((limit - cap_lvl) / (max_z - cap_lvl))
        scale(cap_points, cap_lvl, scale_factor)
        
    elif top_or_bottom == "bottom" and min_z < limit:
        scale_factor = abs((limit - cap_lvl) / (min_z - cap_lvl))
        scale(cap_points, cap_lvl, scale_factor)
##-----------------------------------##



import copy

def execute(all_XZ_outlines, all_YZ_outlines, top_or_bottom="top", tension_arg=0, continuity_arg=0, bias_arg=0):
    if len(all_XZ_outlines) == 0 or len(all_YZ_outlines) == 0:
        return([], [], [])
    
    global tens, cont, bias
    tens = tension_arg
    cont = continuity_arg
    bias = bias_arg

    #----Find outlines that touch the top/bottom of the cell
    cap_lvl = find_min_max_z(outlines=all_XZ_outlines+all_YZ_outlines, top_or_bottom=top_or_bottom)
    XZ_outlines = find_cap_outlines(all_XZ_outlines, cap_lvl)
    YZ_outlines = find_cap_outlines(all_YZ_outlines, cap_lvl)
    #print(len(XZ_outlines), len(YZ_outlines), "outlines touching the", top_or_bottom, "of the cell")

    #---Create arch objects
    create_arches(XZ_outlines, YZ_outlines, top_or_bottom)

    ##---Create cap point object for each
    cap_points = []
    for XZ_line in XZ_outlines:
        #print("X", end = "")
        XZ_arch = identify_arch(XZ_line, top_or_bottom)
        for YZ_line in YZ_outlines:
            #print("Y", end = "")
            intersection = find_intersection(copy.deepcopy(XZ_line), copy.deepcopy(YZ_line), top_or_bottom)
            #print(intersection, end = " ")
            if intersection:
                new_cap_point = CapPoint(copy.deepcopy(XZ_line), copy.deepcopy(YZ_line), top_or_bottom, copy.deepcopy(intersection))
                
                cap_points.append(new_cap_point)
                #Add point positions to the arch
                YZ_arch = identify_arch(YZ_line, top_or_bottom)
                XZ_arch.arch.append(new_cap_point.pos)
                YZ_arch.arch.append(new_cap_point.pos)


    #print(len(cap_points), "cap points created. Expected = ", len(XZ_outlines) * len(YZ_outlines))


    #--Scale the cap points to fit within the limits
    #print("Scaling")
    
    if len(cap_points) == 0:
        XZ_res = []
        YZ_res = []
        
        for XZ_outline in all_XZ_outlines:
            XZ_res.append(XZ_outline)
        for YZ_outline in all_YZ_outlines:
            YZ_res.append(YZ_outline)

        return (cap_points, XZ_res, YZ_res)
    
    
    limit = find_limit(outlines=all_XZ_outlines+all_YZ_outlines,
                       top_or_bottom=top_or_bottom,
                       cap_lvl=cap_lvl)

    scale_cap_points(cap_points=cap_points,
                     cap_lvl=cap_lvl,
                     limit=limit,
                     top_or_bottom=top_or_bottom)
    #-----END SCALING-----

    ##---Final step, recreating all_XZ_outlines and all_YZ_outlines with the cap points on the right outlines
    
    XZ_res = []
    YZ_res = []

    for XZ_outline in all_XZ_outlines:
        arch = identify_arch(XZ_outline, top_or_bottom)
        if arch == None:
            XZ_res.append(XZ_outline)
        else:
            capped = arch.add_to_outline()
            XZ_res.append(capped)

    for YZ_outline in all_YZ_outlines:
        arch = identify_arch(YZ_outline, top_or_bottom)
        if arch == None:
            YZ_res.append(YZ_outline)
        else:
            capped = arch.add_to_outline()
            YZ_res.append(capped)

    return (cap_points, XZ_res, YZ_res)
