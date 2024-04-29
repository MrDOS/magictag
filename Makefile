.PHONY: build
build:
	python3 -m pip wheel --no-deps .

.PHONY: clean
clean:
	rm -rf \
		build/ \
		magictag.egg-info/ \
		magictag-*.whl
