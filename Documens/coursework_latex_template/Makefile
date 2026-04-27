MAIN = paper
TASK = task
LATEX = pdflatex
BIBTEX = bibtex
FLAGS = -interaction=nonstopmode -halt-on-error

SOURCES = $(wildcard *.tex)
BST_FILES = $(wildcard *.bst)
STY_FILES = mospolytech_coursework.sty

.PHONY: all clean

all: $(TASK).pdf $(MAIN).pdf

$(MAIN).pdf: $(SOURCES) $(BST_FILES) $(STY_FILES) $(TASK).pdf
	$(LATEX) $(FLAGS) $(MAIN).tex
	$(BIBTEX) $(MAIN)
	$(LATEX) $(FLAGS) $(MAIN).tex
	$(LATEX) $(FLAGS) $(MAIN).tex

$(TASK).pdf: $(TASK).tex
	$(LATEX) $(FLAGS) $(TASK).tex

clean:
	rm -f *.aux *.log *.out *.toc *.pdf *.bbl *.blg *.run.xml *.bcf
