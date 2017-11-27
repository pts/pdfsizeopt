#! /bin/bash --
# by pts@fazekas.hu at Mon Nov 27 20:28:23 CET 2017
#

set -ex
cd "${0%/*}"
test -f ../pdfsizeopt.single
if ! test -f pdfsizeopt_libexec_extraimgopt_linux.tar.gz; then
  wget -nv -O pdfsizeopt_libexec_extraimgopt_linux.tar.gz.tmp https://github.com/pts/pdfsizeopt/releases/download/2017-01-24/pdfsizeopt_libexec_extraimgopt_linux-v3.tar.gz
  rm -f pdfsizeopt_libexec_extraimgopt_linux.tar.gz
  mv pdfsizeopt_libexec_extraimgopt_linux.tar.gz.tmp pdfsizeopt_libexec_extraimgopt_linux.tar.gz
fi
rm -rf pdfsizeopt_libexec
tar xzvf pdfsizeopt_libexec_extraimgopt_linux.tar.gz
# Doing these chmods early makes the image half as large.
echo chmod 755 pdfsizeopt_libexec/ECT pdfsizeopt_libexec/advpng pdfsizeopt_libexec/optipng pdfsizeopt_libexec/zopflipng
# Reads Dockerfile.
docker build -t ptspts/pdfsizeopt-with-extraimgopt .
rm -rf pdfsizeopt_libexec
: docker push ptspts/pdfsizeopt-with-extraimgopt

: build_docker.sh OK.
