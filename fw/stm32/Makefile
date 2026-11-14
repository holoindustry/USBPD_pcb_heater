# USB-C PCB hot plate firmware, STM32C011F4P6
#
#   make          build/heater.elf .hex .bin, print the size
#   make flash    program over SWD with STM32_Programmer_CLI
#   make test     build and run the host simulation tests
#   make clean

BUILD     := build
TARGET    := $(BUILD)/heater
FLASH_MAX := 12288

CROSS   ?= arm-none-eabi-
CC      := $(CROSS)gcc
OBJCOPY := $(CROSS)objcopy
SIZE    := $(CROSS)size
HOSTCC  ?= gcc
PROGRAMMER ?= $(HOME)/bin/STM32CubeProgrammer/bin/STM32_Programmer_CLI

APP_SRC := src/app.c src/charger.c src/est.c src/fault.c src/led.c src/ntc.c src/pi.c src/sense.c
MCU_SRC := mcu/startup.c mcu/board.c mcu/main.c
APP_HDR := config.h $(wildcard src/*.h)

# ---------------------------------------------------------------- firmware
ARCH    := -mcpu=cortex-m0plus -mthumb
CFLAGS  := $(ARCH) -std=c11 -Os -g -ffunction-sections -fdata-sections -ffreestanding \
           -Wall -Wextra -Werror -DSTM32C011xx -isystem cmsis -I.
LDFLAGS := $(ARCH) -nostartfiles --specs=nano.specs --specs=nosys.specs \
           -T mcu/stm32c011f4.ld -Wl,--gc-sections -Wl,-Map=$(TARGET).map

OBJ := $(patsubst %.c,$(BUILD)/%.o,$(APP_SRC) $(MCU_SRC))

all: $(TARGET).elf $(TARGET).hex $(TARGET).bin size

$(BUILD)/%.o: %.c $(APP_HDR) $(wildcard mcu/*.h) Makefile
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

$(TARGET).elf: $(OBJ) mcu/stm32c011f4.ld
	$(CC) $(LDFLAGS) $(OBJ) -o $@

$(TARGET).hex: $(TARGET).elf
	$(OBJCOPY) -O ihex $< $@

$(TARGET).bin: $(TARGET).elf
	$(OBJCOPY) -O binary $< $@

# flash image = text + data; must stay below FLASH_MAX of the 16 K
size: $(TARGET).elf
	@$(SIZE) $<
	@$(SIZE) $< | awk 'NR == 2 { used = $$1 + $$2; \
	    printf "flash %d of %d bytes allowed (16384 in the part), RAM %d of 6144 bytes + stack\n", used, $(FLASH_MAX), $$2 + $$3; \
	    exit used > $(FLASH_MAX) }'

flash: $(TARGET).hex
	$(PROGRAMMER) -c port=SWD -w $< -v -rst

# -------------------------------------------------------------- host tests
TEST_SRC    := test/test_main.c test/sim.c test/plant.c
TEST_CFLAGS := -std=c11 -O2 -g -Wall -Wextra -fsanitize=address,undefined \
               -fno-sanitize-recover=undefined -fno-omit-frame-pointer -I.

$(BUILD)/host_test: $(APP_SRC) $(TEST_SRC) $(APP_HDR) $(wildcard test/*.h) Makefile
	@mkdir -p $(BUILD)
	$(HOSTCC) $(TEST_CFLAGS) $(APP_SRC) $(TEST_SRC) -lm -o $@

test: $(BUILD)/host_test
	./$(BUILD)/host_test

clean:
	rm -rf $(BUILD)

.PHONY: all size flash test clean
