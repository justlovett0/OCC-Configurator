@echo off
"C:\Program Files\Git\bin\bash.exe" -c "rm -rf build && mkdir build && cd build && cmake -G Ninja .. && ninja"
pause
