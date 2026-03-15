"""
Lexographic Renaming Utility

Pads numeric portions of file or folder names with leading zeros so they
sort in correct lexographic order.  For example, "4.png" becomes "04.png"
when the longest name has 6 characters.

This is needed because Python's os.scandir() returns items in filesystem
order, which sorts "10.png" before "2.png" unless names are zero-padded.

Run this on the timepoints folder before running the pipeline.
"""

import os

# ============================================================================
#  USER CONFIGURATION - Change this before running
# ============================================================================

# Path to the folder containing the timepoint directories.
PATH_TO_TIMEPOINTS = r"C:/Users/tajre/OneDrive/Desktop/Amy Unprocessed/For Talk ForTara"


def rename(path, file_or_folder, name_length):
    """Add leading zeros to file or folder names so they all have the same length.

    Args:
        path:           Directory containing the items to rename.
        file_or_folder: "file" to rename files, "folder" to rename directories.
        name_length:    Target name length, or 'auto' to match the longest name.
    """
    if file_or_folder == "file":
        items = [f.path for f in os.scandir(path) if f.is_file()]
    elif file_or_folder == "folder":
        items = [f.path for f in os.scandir(path) if f.is_dir()]
    else:
        print("file_or_folder must be 'file' or 'folder'")
        return

    if name_length == "auto":
        name_length = max(len(os.path.basename(item)) for item in items)

    for cur_item in items:
        cur_name = os.path.basename(cur_item)
        new_name = list(cur_name)
        if len(new_name) >= name_length:
            continue
        # Find the first numeric character and insert zeros before it
        for i in range(len(new_name)):
            if new_name[i].isnumeric():
                for _ in range(name_length - len(new_name)):
                    new_name.insert(i, "0")
                break
        new_name = "".join(new_name)
        os.rename(
            os.path.join(os.path.normpath(path), cur_name),
            os.path.join(os.path.normpath(path), new_name),
        )


def no_leading_zeros_rename(path, file_or_folder, name_length):
    """Remove leading zeros from file or folder names (inverse of rename).

    Args:
        path:           Directory containing the items to rename.
        file_or_folder: "file" to rename files, "folder" to rename directories.
        name_length:    Target name length (names longer than this get zeros stripped).
    """
    if file_or_folder == "file":
        items = [f.path for f in os.scandir(path) if f.is_file()]
    elif file_or_folder == "folder":
        items = [f.path for f in os.scandir(path) if f.is_dir()]
    else:
        print("file_or_folder must be 'file' or 'folder'")
        return

    for cur_item in items:
        cur_name = os.path.basename(cur_item)
        new_name = list(cur_name)
        if len(new_name) <= name_length:
            continue

        # Find and remove leading zeros
        index_delete_list = []
        for i in range(len(new_name)):
            if new_name[i].isnumeric() and new_name[i] != "0":
                break
            if new_name[i] == "0":
                index_delete_list.append(i)

        for i in range(len(index_delete_list)):
            del new_name[index_delete_list[i] - i]

        new_name = "".join(new_name)
        os.rename(
            os.path.join(os.path.normpath(path), cur_name),
            os.path.join(os.path.normpath(path), new_name),
        )


if __name__ == "__main__":
    target_path = PATH_TO_TIMEPOINTS

    # Rename timepoint folders (e.g. t1 -> t01)
    rename(path=target_path, file_or_folder="folder", name_length="auto")

    # Rename slice files within each timepoint (e.g. 4.png -> 04.png)
    for cur_tp in [f.path for f in os.scandir(target_path) if f.is_dir()]:
        print(cur_tp[-3:], end=" ")
        rename(path=cur_tp, file_or_folder="file", name_length="auto")
