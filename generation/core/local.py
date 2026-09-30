import os


def list_files(folder, recursive=True):
    file_paths = []
    for path in os.listdir(folder):
        full_path = os.path.join(folder, path)
        if os.path.isfile(full_path):
            file_paths.append(full_path)
        elif os.path.isdir(full_path) and recursive:
            file_paths.extend(list_files(full_path))
    return file_paths


