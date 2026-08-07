ffmpeg -y \
    -loop 1 -framerate 24 \
    -i assets/background/background.png \
    -c:v prores \
    -i assets/action/cartoon-dialogue-male-alpha-prores4444.mov \
    -c:v prores \
    -i assets/action/cartoon-dialogue-female-alpha-prores4444.mov \
    -loop 1 -framerate 24 \
    -i 'assets/background/scene2-foreground-alpha-clean-1920x1080_副本.png' \
    -filter_complex '
      [0:v]scale=1920:1080,format=rgba[bg];
      [1:v]scale=735:735,format=rgba[male];
      [2:v]scale=735:735,format=rgba[female];
      [3:v]scale=1920:1080,format=rgba[fg];
      [bg][male]overlay=x=184:y=195:format=auto[tmp1];
      [tmp1][female]overlay=x=999:y=195:format=auto[tmp2];
      [tmp2][fg]overlay=x=0:y=0:format=auto,format=yuv420p[out]
    ' \
    -map '[out]' \
    -frames:v 121 \
    -an \
    -c:v libx264 \
    -preset slow \
    -crf 18 \
    -r 24 \
    -movflags +faststart \
    mvp/output/ffmpeg-layered/cartoon-podcast-new-foreground.mp4