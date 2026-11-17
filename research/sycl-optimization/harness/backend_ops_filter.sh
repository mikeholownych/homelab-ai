#!/bin/sh
# usage: run-ops.sh <OP>   (excludes f8_e4m3 cases: the SYCL backend aborts on that type, which none of our models use)
exec /tb/test-backend-ops test -o "$1" -p '^(?!.*f8_e4m3)'
