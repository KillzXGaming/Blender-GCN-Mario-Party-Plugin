gcc -shared -o lib/lzss.dll lzss.c
gcc -shared -fPIC -O3 -o lib/liblzss.so lzss.c
gcc -shared -fPIC -O3 -o lib/liblzss.dylib lzss.c