import sys
from pathlib import Path

# Add colab-cli path to sys.path so we can import its modules if needed
sys.path.insert(0, "/home/ubuntu/.local/lib/python3.12/site-packages")
from colab_cli.gdrive_auth import drive_auth

def upload():
    print("Authenticating with Google Drive...")
    drive = drive_auth()
    
    # 1. Search for existing 'vfl_training_data' folder in root
    print("Searching for 'vfl_training_data' folder...")
    q = "title = 'vfl_training_data' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    folders = drive.ListFile({'q': q}).GetList()
    
    if folders:
        folder_id = folders[0]['id']
        print(f"Found existing folder 'vfl_training_data' with ID: {folder_id}")
    else:
        print("Folder 'vfl_training_data' not found. Creating it...")
        folder_metadata = {
            'title': 'vfl_training_data',
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [{'id': 'root'}]
        }
        folder = drive.CreateFile(folder_metadata)
        folder.Upload()
        folder_id = folder['id']
        print(f"Created new folder 'vfl_training_data' with ID: {folder_id}")
        
    # 2. Search for existing 'vfl_rich_features.csv' inside this folder and delete/overwrite
    q_file = f"title = 'vfl_rich_features.csv' and '{folder_id}' in parents and trashed = false"
    files = drive.ListFile({'q': q_file}).GetList()
    for f in files:
        print(f"Deleting old file: {f['title']} (ID: {f['id']})")
        f.Delete()
        
    # 3. Upload new file
    csv_path = "/home/ubuntu/faith-workspace/vfl-empire/data/vfl_rich_features.csv"
    print(f"Uploading {csv_path}...")
    file_metadata = {
        'title': 'vfl_rich_features.csv',
        'parents': [{'id': folder_id}]
    }
    file = drive.CreateFile(file_metadata)
    file.SetContentFile(csv_path)
    file.Upload()
    print("Upload complete!")

if __name__ == "__main__":
    upload()
