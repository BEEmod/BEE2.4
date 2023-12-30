rem this batch file uses imagemagick.exe ---> https://imagemagick.org

magick.exe BEE2-2023.png -resize 16x16 BEE2-2023-ico/16.png
magick.exe BEE2-2023.png -resize 32x32 BEE2-2023-ico/32.png
magick.exe BEE2-2023.png -resize 48x48 BEE2-2023-ico/48.png
magick.exe BEE2-2023.png -resize 64x64 BEE2-2023-ico/64.png
magick.exe BEE2-2023.png -resize 128x128 BEE2-2023-ico/128.png
magick.exe BEE2-2023.png -resize 256x256 BEE2-2023-ico/256.png

magick.exe convert BEE2-2023-ico/16.png BEE2-2023-ico/32.png BEE2-2023-ico/48.png BEE2-2023-ico/64.png BEE2-2023-ico/128.png BEE2-2023-ico/256.png BEE2-2023.ico

PAUSE