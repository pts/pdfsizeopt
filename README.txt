README for pdfsizeopt
^^^^^^^^^^^^^^^^^^^^^
pdfsizeopt is a program for converting large PDF files to small ones. More
specifically, pdfsizeopt is a free, cross-platform command-line application
(for Linux, Mac OS X, Windows and Unix) and a collection of best practices
to optimize the size of PDF files, with focus on PDFs created from TeX and
LaTeX documents. pdfsizeopt is written in Python, so it is a bit slow, but
it offloads some of the heavy work to its faster (C, C++ and Java)
dependencies. pdfsizeopt was developed on a Linux system, and it depends on
existing tools such as Python 2.4, Ghostscript 8.50, jbig2enc (optional),
sam2p, pngtopnm, pngout (optional), and the Multivalent PDF compressor
(optional) written in Java.

Doesn't pdfsizeopt work with your PDF?
Report the issue here: https://github.com/pts/pdfsizeopt/issues

Send donations to the author of pdfsizeopt:
https://flattr.com/submit/auto?user_id=pts&url=https://github.com/pts/pdfsizeopt

Installation instructions and usage on Linux
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
There is no installer, you need to run some commands in the command line to
download and install. pdfsizeopt is a command-line only application, there
is no GUI.

To install pdfsizeopt on a Linux system (with architecture i386 or amd64),
open a terminal window and run these commands (without the leading `$'):

  $ mkdir ~/pdfsizeopt
  $ cd ~/pdfsizeopt
  $ wget -O pdfsizeopt_libexec_linux.tar.gz https://github.com/pts/pdfsizeopt/releases/download/2017-01-24/pdfsizeopt_libexec_linux-v3.tar.gz
  $ tar xzvf pdfsizeopt_libexec_linux.tar.gz
  $ wget -O pdfsizeopt https://raw.githubusercontent.com/pts/pdfsizeopt/master/pdfsizeopt.trampoline
  $ chmod +x pdfsizeopt
  $ wget -O pdfsizeopt.single https://raw.githubusercontent.com/pts/pdfsizeopt/master/pdfsizeopt.single
  $ chmod +x pdfsizeopt.single

To optimize a PDF, run the following command

  ~/pdfsizeopt/pdfsizeopt input.pdf output.pdf

If the input PDF has many images or large images, pdfsizeopt can be very
slow. You can speed it up by disabling pngout, the slowest image optimization
method, like this:

  ~/pdfsizeopt/pdfsizeopt --use-pngout=no input.pdf output.pdf

pdfsizeopt creates lots of temporary files (psotmp.*) in the output
directory, but it also cleans up after itself.

It's possible to optimize a PDF outside the current directory. To do that,
specify the pathname (including the directory name) in the command-line.

Please note that the commands above download all dependencies (including
Python and Ghostscript) as well. It's possible to install some of the
dependencies with your package manager, but these steps are considered
alternative and more complicated, and thus are not covered here.

Please note that pdfsizeopt works perfectly on any x86 and amd64 Linux
system. There is no restriction on the libc, Linux distribution etc. because
pdfsizeopt uses only its statically linked x86 executables, and it doesn't
use any external commands (other than pdfsizeopt, pdfsizeopt.single and
pdfsizeopt_libexec/*) on the system. pdfsizeopt also works perfectly on x86
FreeBSD systems with the Linux emulation layer enabled.

To avoid typing ~/pdfsizeopt/pdfsizeopt, add "$HOME/pdfsizeopt" to your PATH
(probably in your ~/.bashrc), open a new terminal window, and the
command pdfsizeopt will work from any directory.

You can also put pdfsizeopt to a directory other than ~/pdfsizeopt , as you
like.

Installation instructions and usage on Windows
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
There is no installer, you need to run some commands in the command line
(black Command Prompt window) to download and install. pdfsizeopt is a
command-line only application, there is no GUI.

Create folder C:\pdfsizeopt, download
https://github.com/pts/pdfsizeopt/releases/download/2017-08-29w/pdfsizeopt_win32exec-v5.zip
, and extract its contents to the folder C:\pdfsizeopt, so that the file
C:\pdfsizeopt\pdfsizeopt.exe exists.

Download
https://raw.githubusercontent.com/pts/pdfsizeopt/master/pdfsizeopt.single
and save it to C:\pdfsizeopt, as C:\pdfsizeopt\pdfsizeopt.single .

To optimize a PDF, run the following command

  C:\pdfsizeopt\pdfsizeopt input.pdf output.pdf

in the command line, which is a black Command Prompt window, you can start
it by Start menu / Run / cmd.exe, or finding Command Prompt in the start
menu.

(Press Tab to get filename completion while typing.)

Since you have to type the input filename as a full pathname, it's
recommended to create a directory with a short name (e.g. C:\pdfs), and copy
the input PDF there first.

If the input PDF has many images or large images, pdfsizeopt can be very
slow. You can speed it up by disabling pngout, the slowest image optimization
method, like this:

  C:\pdfsizeopt\pdfsizeopt --use-pngout=no input.pdf output.pdf

To avoid typing C:\pdfsizeopt\pdfsizeopt, add C:\pdfsizeopt to (the end of)
the system PATH, open a new Command Prompt window, and the command
`pdfsizeopt' will work from any directory.

Depending on your environment, filenames with whitespace, double quotes or
accented characters may not work in the Windows version of pdfsizeopt. To
play it safe, make sure your input and output files have names with letters,
numbers, underscore (_), dash (-), dot (.) and plus (+). The backslash (\)
and the slash (/) are both OK as the directory separator.

You can also put pdfsizeopt to a directory other than C:\pdfsizeopt , but it
won't work if there is whitespace or there are accented characters in any of
the folder names.

Please note that pdfsizeopt works perfectly in Wine (tested with wine-1.2 on
Ubuntu Lucid and wine-1.6.2 on Ubuntu Trusty), but it's a bit slower than
running it natively (as a Linux or Unix program).

Installation instructions and usage on macOS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
There is no installer, you need to run some commands in the command line
(black Command Prompt window) to download and install. pdfsizeopt is a
command-line only application, there is no GUI.

macOS is not one of the officially supported platforms, so installation can
be much more inconvenient (and error-prone) than on Windows or Unix.

Download and extract all the Mac executables and binaries from
https://github.com/pts/pdfsizeopt/releases , and follow the section
``Installation instructions and usage on generic Unix''.

Installation instructions and usage on generic Unix
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
There is no installer, you need to run some commands in the command line
(black Command Prompt window) to download and install. pdfsizeopt is a
command-line only application, there is no GUI.

pdfizeopt is a Python script. It works with Python 2.4, 2.5, 2.6 and 2.7
(but it doesn't work with Python 3.x). So please install Python first.

Create a new directory named pdfsizeopt, and download this link there:

  https://raw.githubusercontent.com/pts/pdfsizeopt/master/pdfsizeopt.single

Rename it to pdfsizeopt and make it executable by running the following
commands (without the leading `$'):

  $ cd pdfsizeopt
  $ mv pdfsizeopt.single pdfsizeopt
  $ chmod +x pdfsizeopt

If your Python executable is not /usr/bin/python, then edit the first line
(starting with `#!') in the pdfsizeopt script accordingly.

Try it with:

  $ ./pdfsizeopt --version
  info: This is pdfsizeopt ZIP rUNKNOWN size=105366.

pdfsizeopt has many dependencies. For full functionality, you need all of
them. Install all of them and put them to the $PATH.

Dependencies:

* Python (command: python). Version 2.4, 2.5, 2.6 and 2.7 work (3.x doesn't
  work).
* Ghostscript (command: gs): Version 9 or newer should work.
* jbig2 (command: jbig2): Install from source:
  https://github.com/pts/pdfsizeopt-jbig2
  If you are unable to install, use pdfsizeopt --use-jbig2=no .
* pngout (command: pngout): Download binaries from here:
  http://www.jonof.id.au/kenutils Source code is not available.
  If you are unable to install, use pdfsizeopt --use-pngout=no .
* png22pnm (command: png22pnm): Install from source:
  https://github.com/pts/tif22pnm
  This is required by sam2p to open PNG files.
  Please note that the bundled tif22pnm command is not needed.
* sam2p (command: sam2p): Install from source:
  https://github.com/pts/sam2p
  If you are unable to install, use pdfsizeopt --do-optimize-images=no .
  Some Linux distributions have sam2p binaries, but they tend to be too old.
  Please use version >=0.49.3.

After installation, use pdfsizeopt as:

  $ ./pdfsizeopt input.pdf output.pdf

You can add the directory containing pdfsizeopt to your $PATH, so the
command `pdfsizeopt' will work from any directory.

Troubleshooting
~~~~~~~~~~~~~~~
1. pdfsizeopt fails for some fonts.
"""""""""""""""""""""""""""""""""""
Specify --do-unify-fonts=no and --do-regenerate-all-fonts=no .

If it still fails, specify -do-optimize-fonts=no .

In either case, please report it on https://github.com/pts/pdfsizeopt/issues

2. pdfsizeopt fails for some images.
""""""""""""""""""""""""""""""""""""
Specify --do-optimize-images=no .

Please report it on https://github.com/pts/pdfsizeopt/issues

3. pdfsizeopt is too slow processing images.
""""""""""""""""""""""""""""""""""""""""""""
Specify --use-pngout=no . This disables pngout, which is the slowest
optimization step for images.

4. pdfsizeopt fails without creating the output PDF.
""""""""""""""""""""""""""""""""""""""""""""""""""""
Please report it on https://github.com/pts/pdfsizeopt/issues , attaching the
input PDF file and the console output of pdfsizeopt. Your report is very
much appreciated.

If pdfsizeopt exits with an uncaught exception, it may leave some temporary
files (psotmp.*) behind in the current directory. You can remove these files.

Please note that pdfsizeopt is not resilient in processing corrupt PDF
files (i.e. those which are not compliant to the PDF standard). So if
pdfsizeopt fails, then the reason may be a bug in pdfsizeopt or a corrupt
PDF input file. Nevertheless, please report an issue (see above).

5. The output PDF of pdfsizeopt doesn't look like the same as the input PDF.
""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""
Please report it on https://github.com/pts/pdfsizeopt/issues , attaching the
input PDF file and the output PDF file (.pso.pdf) and the console output of
pdfsizeopt. Your report is very much appreciated.

6. pdfsizeopt is unable to find some input files on Windows.
""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""
This may happen if the filename or the full pathname contains any character
other than the ASCII letters (a-z and A-Z), digits (0-9), underscore (_),
ASCII dash (-), plus (+), dot (.), backslash (\) or slash (/). Typically
these characters don't work:

* accented characters (such as á and ő)
* whitespace (such as space, tab, newline)
* double quotes (")
* anything which is not ASCII printable (code between 33 and 126, inclusive)

This is unfortunate, and currently the workarounds are:

* renaming or copying the file (and folders) in Windows Explorer, and passing
  the renamed file to pdfsizeopt
* using pdfsizeopt on a Unix system (e.g. Linux, FreeBSD, macOS) instead

The limitation for non-ASCII characters is hard to lift, because cmd.exe
(the Windows Command Prompt) does some destructive transformations affecting
these filenames (especially the characters outside ISO-8859-1, gswin32c.exe
is also affected by them), before even calling pdfsizeopt.

The limitation for whitespace and double quotes is hard to lift, because
Python and msvcrt.dll (used by pdfsizeopt.exe for argv) both do some
destructive transformations on double-quoted argument names. The former can
be worked around by win32api.GetCommandLine(), the latter also needs
GetCommandLIne() to be called from C instead of using argv. These are
doable. Once done, all commands (e.g. gs, sam2p) invoked by pdfsizeopt need
to be updated to add proper quoting with double quotes. This may be easy for
filenames (because only temporary files are passed to those commands, which
don't need any quoting), but not for directory names (especially if the
current directory is a UNC path, see
https://github.com/pts/pdfsizeopt/issues/24). Escaping needs to be
implemented differently for each tool (e.g. gs, sam2p). Good news:
Ghostscript supports double quotes: -sOutputFile="foo bar.pdf"

More documentation
~~~~~~~~~~~~~~~~~~
* https://github.com/pts/pdfsizeopt/releases/download/docs-v1/pts_pdfsizeopt2009.psom.pdf
  White paper on EuroTex 2009.
* https://github.com/pts/pdfsizeopt/releases/download/docs-v1/pts_pdfsizeopt2009_talk.psom.pdf
  Conference talk slides on EuroTex 2009.

__END__
