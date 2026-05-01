# Makefile for the LaTeX report.
#
# Targets:
#   make           build the PDF (default)
#   make watch     rebuild on save (requires latexmk)
#   make clean     remove all build artifacts but keep the PDF
#   make distclean remove the PDF too
#
# Engine: pdflatex via latexmk. Switch to xelatex by passing
# ENGINE=-xelatex on the command line if you need richer Unicode.

DOC      := main
ENGINE   := -pdf
LATEXMK  := latexmk $(ENGINE) -interaction=nonstopmode -file-line-error -halt-on-error

.PHONY: all watch clean distclean

all: $(DOC).pdf

$(DOC).pdf: $(DOC).tex preamble.tex $(wildcard sections/*.tex) $(wildcard figures/*) references.bib
	$(LATEXMK) $(DOC).tex

watch:
	$(LATEXMK) -pvc $(DOC).tex

clean:
	$(LATEXMK) -c

distclean:
	$(LATEXMK) -C
