
from PIL import Image

CHARS = "█▓▒░▐█▇▆▅▄▃▂▁._ "

def print_img2char(path, width=90, gamma=0.9):
    img = Image.open(path).convert("L")  # grayscale
    w, h = img.size
    aspect = h / w
    new_h = int(width * aspect * 0.5)  # 0.5 compensates for character aspect ratio
    img = img.resize((width, new_h))
    #pixels = list(img.get_flattened_data())
    pixels = list(img.getdata())

    lut = [CHARS[int(((i / 255.0) ** gamma) * (len(CHARS) - 1))] for i in range(256)]

    lines = []
    print("#" * 90)
    
    for i in range(0, len(pixels), width):
        if i == 0 or i == 540: 
            lines.append("|" + " " * 88 + "|")
        elif i ==630:
            break
        else:
            row = pixels[i:i+width]
            #line = "".join(CHARS[p * (len(CHARS)-1) // 255] for p in row)
            line = "".join(lut[p] for p in row)
            line = "|" + line[1:-1] + "|"
            lines.append(line)

    logo = "\n".join(lines)
     
    print(logo)
    print("#" * 90)


def header_footer(space=int, string=str) -> str:
    """Return a formatted header and footer for terminal output."""
    line = '=' * space
    gap = " " * space

    sentence = f"{string}"
    centered_sentence = sentence.center(space)
    
    to_print = f"{line}\n{gap}\n{centered_sentence}\n{gap}\n{line}"

    return to_print

def print_end():
    print(" " * 90)
    end_top = "░█▀▀░█▀▀░█▀▄░▀█▀░█▀█░▀█▀░░░█▀▀░█▀█░█▀▄"
    end_mid = "░▀▀█░█░░░█▀▄░░█░░█▀▀░░█░░░░█▀▀░█░█░█░█"
    end_bot = "░▀▀▀░▀▀▀░▀░▀░▀▀▀░▀░░░░▀░░░░▀▀▀░▀░▀░▀▀░"
    print(end_top.center(90, '-'))
    print(end_mid.center(90, '-'))
    print(end_bot.center(90, '-'))
    print(" " * 90)

def print_start():
    print(" " * 90)
    print("-" * 26 + "░█▀▀░█▀▀░█▀▄░▀█▀░█▀█░▀█▀░░░█▀▀░▀█▀░█▀█░█▀▄░▀█▀" + "-" * 26)
    print("-" * 26 + "░▀▀█░█░░░█▀▄░░█░░█▀▀░░█░░░░▀▀█░░█░░█▀█░█▀▄░░█░" + "-" * 26)
    print("-" * 26 + "░▀▀▀░▀▀▀░▀░▀░▀▀▀░▀░░░░▀░░░░▀▀▀░░▀░░▀░▀░▀░▀░░▀░" + "-" * 26)
    print(" " * 90)

def main():
    pass

if __name__ == "__main__":
    main()