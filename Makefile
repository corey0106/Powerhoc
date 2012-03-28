LIBFILES = Worker.cpp util.cpp
LIBOFILES = $(LIBFILES:%.cpp=%.o)
DIR = $(CURDIR)/libhose
INCLUDEDIR = -I$(DIR) -I/opt/local/include
LIBDIR = -L$(DIR) -L/opt/local/lib
OPTS = -g -Wall -Wextra 
LIBS = -lpthread -lzmq -lprotobuf

.phony: all build buildex proto


all:
	build
	buildex

build:
	cd $(DIR); rm -f libhose.a; rm -f *.o
	cd $(DIR); g++ $(OPTS) $(INCLUDEDIR) $(LIBDIR) -c $(LIBFILES)
	cd $(DIR); ar cq libhose.a $(LIBOFILES)

buildex:
	cd examples; rm -f square_worker
	cd examples; g++ -o square_worker square_worker.cpp -lhose $(OPTS) $(INCLUDEDIR) $(LIBDIR) $(LIBS)

test: bin/nosetests
	bin/nosetests -s powerhose

coverage: bin/coverage
	bin/nosetests --with-coverage --cover-html --cover-html-dir=html --cover-package=powerhose


