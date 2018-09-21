import cv2
import numpy as np
import operator
from scipy import optimize
from skimage.segmentation import slic
import matplotlib.pyplot as plt


def fill_holes(mask):
    """
    Fills holes in a given binary mask.
    """
    # noinspection PyUnresolvedReferences
    ret, thresh = cv2.threshold(mask, 1, 255, cv2.THRESH_BINARY)
    # noinspection PyUnresolvedReferences
    new_mask, contours, hierarchy = cv2.findContours(
        thresh,
        cv2.RETR_CCOMP,
        cv2.CHAIN_APPROX_SIMPLE
    )
    for cnt in contours:
        # noinspection PyUnresolvedReferences
        cv2.drawContours(new_mask, [cnt], 0, 255, -1)

    return new_mask


def filter_contours_by_size(mask, min_size=1024, max_size=None):
    # noinspection PyUnresolvedReferences
    ret, thresh = cv2.threshold(mask, 1, 255, cv2.THRESH_BINARY)
    # noinspection PyUnresolvedReferences
    new_mask, contours, hierarchy = cv2.findContours(
        thresh,
        cv2.RETR_CCOMP,
        cv2.CHAIN_APPROX_SIMPLE
    )

    if max_size is None:
        max_size = int(mask.shape[0] * mask.shape[1] * 0.50)
    min_size = min_size

    good_contours = []

    for c in contours:
        # noinspection PyUnresolvedReferences
        rect = cv2.boundingRect(c)
        rect_area = rect[2] * rect[3]

        if max_size >= rect_area >= min_size:
            good_contours.append(c)

    return good_contours


def gaussian(x, height, center, width):
    return height * np.exp(-(x - center) ** 2 / (2 * width ** 2))


def two_gaussian(x, h1, c1, w1, h2, c2, w2):
    return (
        gaussian(x, h1, c1, w1) +
        gaussian(x, h2, c2, w2)
    )


def error_function(p, x, y):
    return (two_gaussian(x, *p) - y) ** 2


def determine_hist_mode(sat_channel):
    cnt, bins = np.histogram(sat_channel.flatten(), bins=256, range=(0, 256))

    maximas = {}

    for i, c in enumerate(cnt[:-1]):
        if cnt[i + 1] < c:
            maximas[i] = c

    maximas = sorted(maximas.items(), key=operator.itemgetter(1))

    if len(maximas) > 1:
        maximas = maximas[-2:]
    else:
        return None

    guess = []

    for m in maximas:
        guess.extend([m[1], m[0], 10])

    optim, success = optimize.leastsq(error_function, guess[:], args=(bins[:-1], cnt))

    min_height = int(sat_channel.shape[0] * sat_channel.shape[1] * 0.01)

    if optim[2] >= optim[-1] and optim[0] > min_height:
        center = optim[1],
        width = optim[2]
    else:
        center = optim[4]
        width = optim[5]

    lower_bound = int(center - width / 2.0)
    upper_bound = int(center + width / 2.0)

    return lower_bound, upper_bound


def find_border_contours(contours, img_h, img_w):
    """
    Given a list of contours, splits them into 2 lists: the border contours and
    non-border contours

    Args:
        contours: list of contours to separate
        img_h: original image height
        img_w: original image width

    Returns:
        2 lists, the first being the border contours

    Raises:
        tbd
    """

    min_y = 0
    min_x = 0

    max_y = img_h - 1
    max_x = img_w - 1

    mins = {min_x, min_y}
    maxs = {max_x, max_y}

    border_contours = []
    non_border_contours = []

    for c in contours:
        # noinspection PyUnresolvedReferences
        rect = cv2.boundingRect(c)

        c_min_x = rect[0]
        c_min_y = rect[1]
        c_max_x = rect[0] + rect[2] - 1
        c_max_y = rect[1] + rect[3] - 1

        c_mins = {c_min_x, c_min_y}
        c_maxs = {c_max_x, c_max_y}

        if len(mins.intersection(c_mins)) > 0 or len(maxs.intersection(c_maxs)) > 0:
            border_contours.append(c)
        else:
            non_border_contours.append(c)

    return border_contours, non_border_contours


def fill_border_contour(contour, img_shape):
    mask = np.zeros(img_shape, dtype=np.uint8)
    # noinspection PyUnresolvedReferences
    cv2.drawContours(mask, [contour], 0, 255, cv2.FILLED)

    # Extract the perimeter pixels, leaving out the last pixel
    # of each side as it is included in the next side (going clockwise).
    # This makes all the side arrays the same length.
    # We also flip the bottom and left side, as we want to "unwrap" the
    # perimeter pixels in a clockwise fashion.
    top = mask[0, :-1]
    right = mask[:-1, -1]
    bottom = np.flipud(mask[-1, 1:])
    left = np.flipud(mask[1:, 0])

    # combine the perimeter sides into one continuous array
    perimeter_pixels = np.concatenate([top, right, bottom, left])

    region_boundary_locs = np.where(perimeter_pixels == 255)[0]

    # the perimeter here is not a geometric perimeter but the number of pixels around the image
    img_h = img_shape[0]
    img_w = img_shape[1]
    perimeter = (img_h - 1) * 2 + (img_w - 1) * 2

    # account for the wrap around from the last contour pixel to the end,
    # i.e. back at the start at (0, 0)
    wrap_distance = region_boundary_locs.max() - perimeter

    # insert the wrap distance in front of the region boundary locations
    region_boundary_locs = np.concatenate([[wrap_distance], region_boundary_locs])

    # calculate the gap size between boundary pixel locations
    gaps = np.diff(region_boundary_locs)

    # if there's only one gap, the contour is already filled
    if not np.sum(gaps > 1) > 1:
        return mask

    # add one to the results because of the diff offset
    max_gap_idx = np.where(gaps == gaps.max())[0] + 1

    # there should only be one, else we have a tie and should probably ignore that case
    if max_gap_idx.size != 1:
        return None

    start_perim_loc_of_flood_entry = region_boundary_locs[max_gap_idx[0]]

    # see if subsequent perimeter locations were also part of the contour,
    # adding one to the last one we found
    subsequent_region_border_locs = region_boundary_locs[
        region_boundary_locs > start_perim_loc_of_flood_entry
    ]

    flood_fill_entry_point = start_perim_loc_of_flood_entry

    for loc in subsequent_region_border_locs:
        if loc == flood_fill_entry_point + 1:
            flood_fill_entry_point = loc

    # we should hit the first interior empty point of the contour
    # by moving forward one pixel around the perimeter
    flood_fill_entry_point += 1

    # now to convert our perimeter location back to an image coordinate
    if flood_fill_entry_point < img_w:
        flood_fill_entry_coords = (flood_fill_entry_point, 0)
    elif flood_fill_entry_point < img_w + img_h:
        flood_fill_entry_coords = (img_w - 1, flood_fill_entry_point - img_w + 1)
    elif flood_fill_entry_point < img_w * 2 + img_h:
        flood_fill_entry_coords = (img_h + (2 * img_w) - 3 - flood_fill_entry_point, img_h - 1)
    else:
        flood_fill_entry_coords = (0, perimeter - flood_fill_entry_point)

    flood_fill_mask = np.zeros((mask.shape[0] + 2, mask.shape[1] + 2), dtype=np.uint8)

    # noinspection PyUnresolvedReferences
    cv2.floodFill(mask, flood_fill_mask, tuple(flood_fill_entry_coords), 255)

    return mask


def find_contour_union(contour_list, img_shape):
    union_mask = np.zeros(img_shape, dtype=np.uint8)

    for c in contour_list:
        c_mask = np.zeros(img_shape, dtype=np.uint8)
        # noinspection PyUnresolvedReferences
        cv2.drawContours(c_mask, [c], 0, 255, cv2.FILLED)
        # noinspection PyUnresolvedReferences
        union_mask = cv2.bitwise_or(union_mask, c_mask)

    return union_mask


def generate_background_contours(
        hsv_img,
        non_bg_contours,
        remove_border_contours=True,
        plot=False
):
    img = cv2.cvtColor(hsv_img, cv2.COLOR_HSV2RGB)
    non_bg_mask = np.zeros((img.shape[0], img.shape[1]), dtype=np.uint8)
    cv2.drawContours(non_bg_mask, non_bg_contours, -1, 255, cv2.FILLED)

    bg_mask_img = cv2.bitwise_and(img, img, mask=~non_bg_mask)

    segments = slic(
        bg_mask_img,
        n_segments=200,  # TODO: need to calculate this instead of hard-coding
        compactness=100,
        sigma=1,
        enforce_connectivity=True
    )

    masked_segments = cv2.bitwise_and(segments, segments, mask=~non_bg_mask)

    all_contours = []

    for label in np.unique(masked_segments):
        if label == 0:
            continue

        mask = masked_segments == label
        mask.dtype = np.uint8
        mask[mask == 1] = 255
        mask = cv2.erode(mask, np.ones((3, 3), np.uint8), iterations=3)

        new_mask, contours, hierarchy = cv2.findContours(
            mask,
            cv2.RETR_CCOMP,
            cv2.CHAIN_APPROX_SIMPLE
        )

        all_contours.extend(contours)

    bkgd_contour_mask = np.zeros((img.shape[0], img.shape[1]), dtype=np.uint8)
    cv2.drawContours(bkgd_contour_mask, all_contours, -1, 255, -1)

    all_contours = filter_contours_by_size(
        bkgd_contour_mask, min_size=64 * 64,
        max_size=1000 * 1000
    )

    if remove_border_contours:
        border_contours, all_contours = find_border_contours(
            all_contours,
            img.shape[0],
            img.shape[1]
        )

    if plot:
        bkgd_contour_mask = np.zeros((img.shape[0], img.shape[1]), dtype=np.uint8)
        cv2.drawContours(bkgd_contour_mask, all_contours, -1, 255, -1)

        fig = plt.figure(figsize=(16, 16))
        plt.imshow(cv2.cvtColor(bkgd_contour_mask, cv2.COLOR_GRAY2RGB))

        bg_mask_img = cv2.bitwise_and(img, img, mask=bkgd_contour_mask)
        fig = plt.figure(figsize=(16, 16))
        plt.imshow(bg_mask_img)

        plt.show()

    return all_contours


def elongate_contour(contour, img_shape, extend_length):
    c_mask = np.zeros(img_shape, dtype=np.uint8)

    cv2.drawContours(c_mask, [contour], -1, 255, -1)

    rect = cv2.minAreaRect(contour)
    box = box = cv2.boxPoints(rect)

    cx, cy = rect[0]
    w, h = rect[1]
    angle = rect[2]

    if w <= 1 or h <= 1 or extend_length < 0:
        return contour

    if isinstance(extend_length, float) and extend_length <= 1.0:
        extend_length = int(extend_length * max(w, h)) + 1

    if w > h:
        angle = angle - 90

    mat = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
    c_mask_rot = cv2.warpAffine(c_mask, mat, img_shape)
    c_mask_rot[c_mask_rot > 0] = 255

    y_locs = np.where(c_mask_rot > 0)[0]
    y_min = y_locs.min()
    y_max = y_locs.max()
    y_mid = int(np.round(np.average([y_min, y_max])))

    top_x_locs = np.where(c_mask_rot[y_min + 1, :] > 0)[0]
    mid_x_locs = np.where(c_mask_rot[y_mid, :] > 0)[0]
    bottom_x_locs = np.where(c_mask_rot[y_max - 1, :] > 0)[0]

    mid_x_min = mid_x_locs.min()
    mid_x_max = mid_x_locs.max()
    mid_x_mid = int(np.round(np.average([mid_x_min, mid_x_max])))
    mid_width = mid_x_max - mid_x_min

    if len(top_x_locs) > 0:
        top_x_min = top_x_locs.min()
        top_x_max = top_x_locs.max()
        top_x_mid = int(np.round(np.average([top_x_min, top_x_max])))
        extend_top = True
    else:
        extend_top = False

    if len(bottom_x_locs) > 0:
        bottom_x_min = bottom_x_locs.min()
        bottom_x_max = bottom_x_locs.max()
        bottom_x_mid = int(np.round(np.average([bottom_x_min, bottom_x_max])))
        extend_bottom = True
    else:
        extend_bottom = False

    mid_coord = (mid_x_mid, y_mid)
    new_c_mask_rot = c_mask_rot.copy()

    if extend_top:
        top_coord = (top_x_mid, y_min)

        top_angle = np.math.atan2(top_coord[1] - mid_coord[1], top_coord[0] - mid_coord[0])
        top_angle = top_angle * 180 / np.pi

        cv2.ellipse(
            new_c_mask_rot,
            top_coord,
            (extend_length, int(mid_width / 4)),
            top_angle,
            0,
            360,
            255,
            -1
        )

    if extend_bottom:
        bottom_coord = (bottom_x_mid, y_max)

        bottom_angle = np.math.atan2(bottom_coord[1] - mid_coord[1],
                                     bottom_coord[0] - mid_coord[0])
        bottom_angle = bottom_angle * 180 / np.pi

        cv2.ellipse(
            new_c_mask_rot,
            bottom_coord,
            (extend_length, int(mid_width / 4)),
            bottom_angle,
            0,
            360,
            255,
            -1
        )

    inv_mat = cv2.getRotationMatrix2D((cx, cy), -angle, 1.0)
    c_mask_new = cv2.warpAffine(new_c_mask_rot, inv_mat, img_shape)
    # fix interpolation artifacts
    c_mask_new[c_mask_new > 0] = 255

    _, contours, hierarchy = cv2.findContours(c_mask_new.copy(), cv2.RETR_EXTERNAL,
                                              cv2.CHAIN_APPROX_SIMPLE)

    return contours[0]
