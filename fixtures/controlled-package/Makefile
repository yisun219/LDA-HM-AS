CC ?= cc
CFLAGS ?= -O2 -g -fPIC -Wall -Wextra -Werror
LDFLAGS ?=
PREFIX ?= /usr
LIBDIR ?= $(PREFIX)/lib

all: liblda-fixture.so.1.0 test-fixture

liblda-fixture.so.1.0: src/lda_fixture.c include/lda_fixture.h
	$(CC) $(CPPFLAGS) $(CFLAGS) -Iinclude -shared -Wl,-soname,liblda-fixture.so.1 -o $@ src/lda_fixture.c $(LDFLAGS)

test-fixture: tests/test_fixture.c liblda-fixture.so.1.0
	ln -sf liblda-fixture.so.1.0 liblda-fixture.so
	$(CC) $(CPPFLAGS) $(CFLAGS) -Iinclude -o $@ tests/test_fixture.c -L. -Wl,-rpath,'$$ORIGIN' -llda-fixture

check: all
	LD_LIBRARY_PATH=. ./test-fixture

install: all
	install -d $(DESTDIR)$(LIBDIR) $(DESTDIR)$(PREFIX)/include $(DESTDIR)$(LIBDIR)/pkgconfig $(DESTDIR)$(LIBDIR)/cmake/LDAFixture
	install -m 0755 liblda-fixture.so.1.0 $(DESTDIR)$(LIBDIR)/
	ln -sf liblda-fixture.so.1.0 $(DESTDIR)$(LIBDIR)/liblda-fixture.so.1
	ln -sf liblda-fixture.so.1 $(DESTDIR)$(LIBDIR)/liblda-fixture.so
	install -m 0644 include/lda_fixture.h $(DESTDIR)$(PREFIX)/include/
	printf '%s\n' 'prefix=/usr' 'libdir=$${prefix}/lib' 'includedir=$${prefix}/include' '' 'Name: lda-fixture' 'Description: LDA controlled ABI fixture' 'Version: 1.0' 'Libs: -L$${libdir} -llda-fixture' 'Cflags: -I$${includedir}' >$(DESTDIR)$(LIBDIR)/pkgconfig/lda-fixture.pc
	printf '%s\n' 'add_library(LDAFixture::LDAFixture SHARED IMPORTED)' 'set_target_properties(LDAFixture::LDAFixture PROPERTIES IMPORTED_LOCATION "/usr/lib/liblda-fixture.so.1" INTERFACE_INCLUDE_DIRECTORIES "/usr/include")' >$(DESTDIR)$(LIBDIR)/cmake/LDAFixture/LDAFixtureConfig.cmake

clean:
	rm -f liblda-fixture.so liblda-fixture.so.1 liblda-fixture.so.1.0 test-fixture
