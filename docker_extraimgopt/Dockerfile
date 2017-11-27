# by pts@fazekas.hu at docker push ptspts/pdfsizeopt
#
# Run:
#
#   $ docker run -v "$PWD:/workdir" -u "$(id -u):$(id -g)" --rm -it ptspts/pdfsizeopt-with-extraimgopt pdfsizeopt --use-image-optimizer=sam2p,jbig2,pngout,zopflipng,optipng,advpng,ECT input.pdf output.pdf
#
# Building in a separate `context' directory so that only a few bytes have
# to be sent to the Docker daemon.
#

FROM ptspts/pdfsizeopt
MAINTAINER pts@fazekas.hu
LABEL version=1
ADD pdfsizeopt_libexec/ECT pdfsizeopt_libexec/advpng pdfsizeopt_libexec/optipng pdfsizeopt_libexec/zopflipng /bin/
