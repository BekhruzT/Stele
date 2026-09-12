import os
import json
from pathlib import Path
import shutil


def save_to_file(content, file_path):
    with open(file_path, "w", encoding="utf-8") as fp:
        fp.write(str(content))


def list_files_with_prefix(directory, prefix):
    result = []
    for filename in os.listdir(directory):
        # check if the current filename starts with the prefix
        if filename.startswith(prefix):
            result.append(filename)
    return result


def list_files_with_suffix(directory, prefix):
    result = []
    print(os.path.abspath(directory))
    for filename in os.listdir(directory):
        print(filename)
        # check if the current filename starts with the prefix
        if filename.endswith(prefix):
            result.append(filename)
    return result


def load_json(path):
    with open(path, "r") as fp:
        return json.load(fp)


def list_files(folder, recursive=True):
    file_paths = []
    for path in os.listdir(folder):
        full_path = os.path.join(folder, path)
        if os.path.isfile(full_path):
            file_paths.append(full_path)
        elif os.path.isdir(full_path) and recursive:
            file_paths.extend(list_files(full_path))
    return file_paths


def save_json(content, file_path):
    with open(file_path, "w") as f:
        f.write(json.dumps(content, indent=4))


def ensure_dir(dir_path):
    Path(dir_path).mkdir(exist_ok=True, parents=True)


def read_file(path):
    with open(path, "r",  encoding='utf-8') as fp:
        return fp.read()


def copy_to_same_dir(src_file_path, dest_file_name):
    directory, _ = os.path.split(src_file_path)
    new_file_path = os.path.join(directory, dest_file_name)
    shutil.copy(src_file_path, new_file_path)
    return new_file_path


def copy_file(src_file_path, dest_file_path):
    shutil.copy(src_file_path, dest_file_path)


def remove_files(file_paths):
    for file_path in file_paths:
        os.remove(file_path)


def rename_file(old_name, new_name):
    os.rename(old_name, new_name)


def remove_dir(dir_path):
    shutil.rmtree(dir_path)
