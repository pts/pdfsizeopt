# by pts@fazekas.hu at Wed Oct 11 15:24:03 CEST 2017
#
# Run:
#
#   $ docker run -v "$PWD:/workdir" -u "$(id -u):$(id -g)" --rm -it ptspts/pdfsizeopt pdfsizeopt input.pdf output.pdf
#
# Building in a separate `context' directory so that only a few bytes have
# to be sent to the Docker daemon.
#

FROM scratch
MAINTAINER pts@fazekas.hu
LABEL version=1
CMD ["sh"]
ADD busybox /bin/
#RUN ["busybox", "chmod", "755", "/bin/busybox"]
RUN ["busybox", "ln", "-s", "/", "/usr"]
RUN ["busybox", "--install", "-s"]

ADD pdfsizeopt_libexec/gs pdfsizeopt_libexec/jbig2 pdfsizeopt_libexec/png22pnm pdfsizeopt_libexec/sam2p pdfsizeopt_libexec/pngout pdfsizeopt_libexec/python /bin/
#RUN cd /bin && chmod 755 gs jbig2 png22pnm sam2p pngout python
# Run this ADD last, to improve caching.
ADD pdfsizeopt.single /bin/pdfsizeopt
#RUN cd /bin && chmod 755 pdfsizeopt
WORKDIR /workdir
