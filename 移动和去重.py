import os
import shutil
import hashlib
import sys

def ensure_unique_filename(target_directory, original_filename):
    """
    If a file with the same name already exists in the target directory,
    append _1, _2, ... before the file extension to make the name unique.
    """
    base_name, extension = os.path.splitext(original_filename)
    counter = 1
    candidate_name = original_filename
    while os.path.exists(os.path.join(target_directory, candidate_name)):
        candidate_name = f"{base_name}_{counter}{extension}"
        counter += 1
    return candidate_name

def compute_file_hash(file_path, chunk_size=8192):
    """
    Compute the MD5 hash of a file for duplicate detection.
    """
    hasher = hashlib.md5()
    with open(file_path, "rb") as file:
        for chunk in iter(lambda: file.read(chunk_size), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

def prompt_user_confirmation(message, default_no=True):
    """
    Prompt the user with a yes/no question. Returns True for yes, False for no.
    """
    default_prompt = "Y/n" if not default_no else "y/N"
    response = input(f"{message} ({default_prompt}): ").strip().lower()
    if not response:
        return not default_no
    return response in ("y", "yes")

def gather_files_by_extensions(source_directories, extensions_set):
    """
    Walk through the list of source directories and collect all files
    whose extensions are in extensions_set.
    """
    collected_file_paths = []
    for directory in source_directories:
        for root, _, file_names in os.walk(directory):
            for name in file_names:
                if os.path.splitext(name)[1].lower() in extensions_set:
                    collected_file_paths.append(os.path.join(root, name))
    return collected_file_paths

def main():
    # Step 1: Gather user inputs
    source_input = input("Enter source directories (separated by commas): ").strip()
    if not source_input:
        print("No source directories provided. Exiting.")
        sys.exit(1)
    source_directory_list = [path.strip() for path in source_input.split(",")]

    destination_root_directory = input("Enter the destination root directory: ").strip()
    if not destination_root_directory:
        print("No destination directory provided. Exiting.")
        sys.exit(1)

    should_move_files = prompt_user_confirmation(
        "Do you want to move files instead of copying them?", default_no=False
    )
    action_verb = "move" if should_move_files else "copy"

    # Step 2: Define file type extensions
    image_extensions = {".jpg", ".jpeg", ".png", ".gif", ".bmp"}
    video_extensions = {".mp4", ".avi", ".mkv", ".mov"}
    document_extensions = {".txt", ".md", ".doc", ".docx", ".pdf"}

    # Step 3: Collect files
    image_file_paths = gather_files_by_extensions(source_directory_list, image_extensions)
    video_file_paths = gather_files_by_extensions(source_directory_list, video_extensions)
    document_file_paths = gather_files_by_extensions(source_directory_list, document_extensions)

    print(f"Found {len(image_file_paths)} images, {len(video_file_paths)} videos, and {len(document_file_paths)} documents.")
    if not prompt_user_confirmation(f"Proceed to {action_verb} these files?", default_no=False):
        print("Operation canceled by user. Exiting.")
        return

    # Step 4: Create categorized subdirectories
    images_directory = os.path.join(destination_root_directory, "Images")
    videos_directory = os.path.join(destination_root_directory, "Videos")
    documents_directory = os.path.join(destination_root_directory, "Documents")
    for directory in (images_directory, videos_directory, documents_directory):
        os.makedirs(directory, exist_ok=True)

    # Step 5: Perform copy or move, ensuring unique filenames
    for source_path, target_directory in (
        [(path, images_directory) for path in image_file_paths] +
        [(path, videos_directory) for path in video_file_paths] +
        [(path, documents_directory) for path in document_file_paths]
    ):
        original_name = os.path.basename(source_path)
        unique_name = ensure_unique_filename(target_directory, original_name)
        destination_path = os.path.join(target_directory, unique_name)
        if should_move_files:
            shutil.move(source_path, destination_path)
        else:
            shutil.copy2(source_path, destination_path)

    print(f"Files have been successfully {action_verb}d to their respective folders.")
    print("Duplicate filenames in the destination were handled by appending numbers.")

    # Step 6: Optional duplicate removal by file content
    if prompt_user_confirmation("Would you like to remove duplicate files by content hash?", default_no=False):
        total_removed = 0
        for directory in (images_directory, videos_directory, documents_directory):
            hash_to_paths = {}
            for root, _, file_names in os.walk(directory):
                for name in file_names:
                    full_path = os.path.join(root, name)
                    file_hash = compute_file_hash(full_path)
                    hash_to_paths.setdefault(file_hash, []).append(full_path)
            for duplicate_list in hash_to_paths.values():
                for duplicate_path in duplicate_list[1:]:
                    os.remove(duplicate_path)
                    total_removed += 1
        print(f"Duplicate removal complete. {total_removed} files were deleted.")
    else:
        print("Skipped duplicate removal step.")

if __name__ == "__main__":
    main()




