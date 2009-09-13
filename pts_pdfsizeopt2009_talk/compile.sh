#! /bin/bash
set -ex
pdflatex pts_pdfsizeopt2009_talk.tex 
pdflatex pts_pdfsizeopt2009_talk.tex 
../pdfsizeopt.py pts_pdfsizeopt2009_talk.pdf
cp pts_pdfsizeopt2009_talk.pdf ~/Dropbox.pts/Dropbox/Public/
