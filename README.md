# EXIF_STRIP – Cross-Platform Image Metadata Remover
Cross-platform Flask web app to preview and remove EXIF, GPS, ICC, XMP, and other metadata from images without quality loss. Supports JPEG, PNG, GIF, WebP, TIFF, HEIC/AVIF, and more with drag-and-drop bulk processing and one-click ZIP download for cleaned files.
## ✨ Features
- **🖼 Wide Format Support** – JPEG, PNG, GIF, WebP, TIFF, BMP, HEIC/HEIF, AVIF, and more
- **🔍 Metadata Preview** – See exactly what metadata is embedded before removing it
- **📍 GPS Data Removal** – Detect and strip embedded location info
- **✂ Lossless JPEG Cleaning** – Removes EXIF without recompressing when possible
- **📦 Bulk Processing** – Drag-and-drop multiple images and download as a single ZIP
- **💻 Cross-Platform** – Works on Linux, macOS, and Windows using provided setup scripts
## 🚀 Installation
### Linux / macOS:
```bash
chmod +x linux.sh  # or mac.sh
./linux.sh         # or ./mac.sh
```
### Windows:
```powershell
.\Windows.ps1
```
These scripts will:
1. Install Python 3 (if missing)
2. Create a virtual environment
3. Install dependencies
4. Start the web app
## 📖 Usage
1. Run the setup script for your OS
2. Open your browser at: `http://127.0.0.1:5000`
3. Drag & drop images or select manually
4. Click **View metadata** to inspect
5. Enable *"Remove all metadata"* for ICC/XMP/etc removal
6. Click **Clean & Download** to get a ZIP of cleaned files
## 📷 Supported Formats
| Category           | Extensions                          |
|--------------------|-------------------------------------|
| Raster formats     | .jpg, .jpeg, .png, .gif, .webp, .tif, .tiff, .bmp |
| High-efficiency    | .heic, .heif, .avif (requires pillow-heif) |
## 🔗 Community & Socials
- **📹 TikTok**: [@RawdogReverend](https://tiktok.com/@RawdogReverend)
- **💬 Discord**: [Join the server](https://discord.gg/5kVgDpCVD9)
## 🛠 Tech Stack
- Python (Flask)
- Pillow + pillow-heif for image handling
- piexif for lossless EXIF removal
- Vanilla JS for drag-and-drop UI
## ❤️ Support the Project
If you find this tool useful:
- Share with friends
- Post about it on [TikTok](https://tiktok.com/@RawdogReverend)
- Join my [Discord](https://discord.gg/5kVgDpCVD9) to give feedback
