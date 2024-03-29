#! /usr/bin/env python
from __future__ import print_function
import ipdb
import re
import sys

#MEM_SIZE = 52428800  # 50 MB
MEM_SIZE = 51200   # 50 kB
REGISTER_COUNT = 15
pc = 10

directive_re = re.compile(r"((?P<label>[a-zA-Z0-9]+)\s+)?((?P<type>\.[a-zA-Z]+)\s+)(?P<value>(-?[0-9]+)|'(.{1,2})')")
instruction_re = re.compile(r"^((?P<label>[A-Za-z0-9]+)\s+)??(?P<instruction>[A-Za-z]{2,3})\s+(((?P<single_code>\d+)|(?P<single_reg>[rR]\d+|pc|sp|st|sb|fp)|(?P<single_lbl>[a-zA-Z0-9]{2,}))|(?P<op_one>[rR]\d+|pc|sp|st|sb|fp)\s+((?P<d_num>#(-)?\d+)|(?P<op_reg>[rR]\d+|pc|sp|st|sb|fp)|(?P<op_label>[A-Za-z0-9]+)))(\s*(;.*)?)?$")

I_CODE = {
    "TRP": 0,
    "ADD": 1,
    "ADI": 2,
    "SUB": 3,
    "MUL": 4,
    "DIV": 5,
    "AND": 6,
    "OR": 7,
    "CMP": 8,
    "MOV": 9,
    "LDA": 10,
    "STR": 11,
    "LDR": 12,
    "STB": 13,
    "LDB": 14,
    "JMP": 15,
    "JMR": 16,
    "BNZ": 17,
    "BGT": 18,
    "BLT": 19,
    "BRZ": 20,
    "LDBI": 21,
    "STBI": 22,
    "LDRI": 23,
    "STRI": 24,
}

# Define reserved symbols
RESERVED = []
for _ in range(REGISTER_COUNT):
    RESERVED.append("r{}".format(_))
    RESERVED.append("R{}".format(_))
RESERVED.append("pc")
RESERVED.append("st")
RESERVED.append("sb")
RESERVED.append("sp")
RESERVED.append("fp")
RESERVED = RESERVED + I_CODE.keys()

SPECIAL_REGISTERS = {
    "pc": 10,
    "sp": 11,
    "st": 12,
    "sb": 13,
    "fp": 14
}

class DuplicateLabelError(Exception): pass
class UndefinedLabelError(Exception): pass
class ReservedKeywordError(Exception): pass
class UnknownInstructionError(Exception): pass
class UnknownDirectiveError(Exception): pass
class DirectiveInInstructionsError(Exception): pass
class UnknownTrapError(Exception): pass


def _twos(val, bits):
    if ((val & (1 << (bits-1))) != 0):
        val = val-(1 << bits)
    return val


def int_to_block(i):
    try:
        d = (i & 0b11111111)
        c = ((i >> 8) & 0b11111111)
        b = ((i >> 16) & 0b11111111)
        a = ((i >> 24) & 0b11111111)
        return a, b, c, d
    except TypeError as e:
        raise Exception("Error writing int to memory. Argument: " + str(i))


def block_to_bin(b):
    return (b[0] << 24) + (b[1] << 16) + (b[2] << 8) + b[3]


class MemoryManager:
    memory = None

    def __init__(self, size=MEM_SIZE):
        self.memory = bytearray(size)

    def __repr__(self):
        return str(self.memory)

    def store_int(self, i, loc):
        result = int_to_block(i)
        for byte in result:
            self.memory[loc] = byte
            loc = loc + 1
        return loc

    def fetch_int(self, loc):
        bytes = []
        for i in range(4):
            bytes.append(self.memory[loc])
            loc = loc + 1
        return (_twos(block_to_bin(bytes), 32))

    def store_char(self, ch, loc):
        self.memory[loc] = ch

    def fetch_char(self, loc):
        return self.memory[loc]

    def store_inst(self, loc, code, op1, op2=None):
        self.store_int(code, loc)
        self.store_int(op1, loc+4)
        self.store_int(op2 or 0, loc+8)

    def fetch_inst(self, loc):
        i = self.fetch_int(loc)
        o1 = self.fetch_int(loc+4)
        o2 = self.fetch_int(loc+8)
        return (i, o1, o2)


class Assembler:
    symbol_table = dict()
    memory = MemoryManager()
    pc = 0
    source = None

    def read(self, filename):
        self.source = open(filename, 'r')

    def reset_source(self):
        self.source.seek(0)

    def first_pass(self):
        line_number = 1
        for line in self.source:
            line = line.strip()
            directive = directive_re.search(line)
            instruction = instruction_re.search(line)
            if line and not line[0] == ';':
                pc_plus = 1
                if directive and directive.groupdict()['type']:
                    result = directive.groupdict()
                    if result['label']:
                        if result['label'] in RESERVED:
                            raise ReservedKeywordError(
                                'Line ' + str(line_number) + ': [' +
                                result['label'] + '] | ' + line
                            )
                        label = self.symbol_table.get(result['label'])
                        if label:
                            raise DuplicateLabelError(
                                'Line ' + str(line_number) +  ': [' +
                                result['label'] + '] | ' + line)
                        else:
                            self.symbol_table[result['label']] = \
                                (self.pc, [line_number])
                    if result['type'].upper() == '.INT':
                        pc_plus = 4
                elif instruction and instruction.groupdict()['instruction']:
                    pc_plus = 12
                    result = instruction.groupdict()
                    declare_label = result.get('label')
                    use_label = result.get('op_label') or result.get('single_lbl')
                    if declare_label:
                        if declare_label in RESERVED:
                            raise ReservedKeywordError(
                                'Line ' + str(line_number) + ': [' +
                                declare_label + '] | ' + line
                            )
                        label = self.symbol_table.get(declare_label)
                        if label:
                            if label[0]:
                                raise DuplicateLabelError(
                                    'Line ' + str(line_number) + ': [' +
                                    label + '] | ' + line
                                )
                            self.symbol_table[result['label']] = (self.pc, label[1])
                        else:
                            self.symbol_table[result['label']] = \
                                (self.pc, [])
                    if use_label:
                        try:
                            self.symbol_table[use_label][1].append(line_number)
                        except KeyError:
                            self.symbol_table[use_label] = (None,[line_number])
                else:
                    raise UnknownInstructionError(
                        'Line ' + str(line_number) + ': ' + line)

                # Not a comment, increment PC
                self.pc = self.pc + pc_plus

            line_number = line_number + 1

        # Check for labels with no declaration
        bad_labels = [_ for _ in self.symbol_table if
            self.symbol_table[_][0] is None]
        if bad_labels:
            msg = "Unknown labels:\n"
            for _ in bad_labels:
                msg = (msg + "\t" + str(_) + " on lines:" +
                      str(self.symbol_table[_][1]) + "\n")
            raise UndefinedLabelError(msg)

    def second_pass(self):
        self.reset_source()
        self.pc = 0
        line_number = 1
        self.code_seg = None

        def store_int(val):
            self.memory.store_int(int(val), self.pc)
            self.pc = self.pc + 4

        def store_char(val):
            if val == "'\\n'":
                val = val.replace('\\n', '\n')
            elif val == "'\\0'":
                val = val.replace('\\0', '\0')
            elif val == "'\\t'":
                val = val.replace('\\t', '\t')
            self.memory.store_char(val.replace("'", ""), self.pc)
            self.pc = self.pc + 1

        ACTIONS = {
            '.INT': store_int,
            '.BYT': store_char
        }

        INDIRECTABLE = ['LDB', 'LDR', 'STB', 'STR']

        for line in self.source:
            line = line.strip()
            directive = directive_re.search(line)
            instruction = instruction_re.search(line)
            if line and not line[0] == ';':
                if directive and directive.groupdict()['type']:
                    pc_diff = 1
                    if self.code_seg is not None:
                        raise DirectiveInInstructionsError(
                            'Line ' + str(line_number) + ': ' + line)
                    result = directive.groupdict()
                    try:
                        ACTIONS[result['type'].upper()](result['value'])
                    except KeyError:
                        raise UnknownDirectiveError(
                        'Line ' + str(line_number) + ': [' + result['type'] +
                        '] ' + line);
                elif instruction and instruction.groupdict()['instruction']:
                    # TODO: Instruction rigidity
                    if self.code_seg is None:
                        self.code_seg = self.pc
                    result = instruction.groupdict()
                    try:
                        pc_diff = 12
                        i = result['instruction'].upper()
                        if result['single_code']:
                            op = int(result['single_code'])
                            self.memory.store_inst(self.pc, I_CODE[i], op)
                        elif result['single_reg']:
                            op = int(SPECIAL_REGISTERS.get(
                                result['single_reg'],
                                result['single_reg'][1:]))
                            self.memory.store_inst(self.pc, I_CODE[i], op)
                        elif result['single_lbl']:
                            # resolve address
                            try:
                                op = self.symbol_table[result['single_lbl']][0]
                            except KeyError:
                                raise UndefinedLabelError(
                                    'PC: ' + str(self.pc) +
                                    '. [' + result['single_lbl'] + ']')
                            self.memory.store_inst(self.pc, I_CODE[i], op)
                        else:
                            op1 = int(SPECIAL_REGISTERS.get(
                                result['op_one'],
                                result['op_one'][1:]))
                            if result['d_num']:
                                op2 = int(result['d_num'][1:])
                            elif result['op_reg']:
                                if i in INDIRECTABLE:
                                    i = i + 'I'
                                op2 = int(SPECIAL_REGISTERS.get(
                                    result['op_reg'],
                                    result['op_reg'][1:]))
                            elif result['op_label']:
                                # lookup
                                try:
                                    op2 = self.symbol_table[result['op_label']][0]
                                except KeyError:
                                    raise UndefinedLabelError(
                                        'PC: ' + str(self.pc) +
                                        '. [' + result['single_lbl'] + ']')
                            self.memory.store_inst(
                                self.pc, I_CODE[i], op1, op2)
                    except KeyError as e:
                        raise UnknownInstructionError('PC: ' + str(self.pc) +
                                                      '. ' + e.message)

                    self.pc = self.pc + pc_diff
                else:
                    raise UnknownInstructionError(
                        'Line ' + str(line_number) + ': ' + line)

            line_number = line_number + 1
        self.stack_top = self.pc


class VirtualMachine:
    registers = dict()
    zero_flag = 0
    memory = None
    input_buffer = ""

    def TRP(self, code, na):
        options = {
            0: lambda : sys.exit(0), # fin.
            1: lambda : print(self.registers[0].fetch_int(0), end=""), # print int
            2: self.getint,
            3: lambda : print(chr(self.registers[0].fetch_char(3)), end=""), # print char
            4: self.getchar,
            99: ipdb.set_trace
        }
        try:
            options[code]()
        except KeyError:
            raise UnknownTrapError('Code: ' + str(code) +
                                   '. PC: ' + str(self.registers[11].fetch_int(0)) + '.')

    def getint(self):
        if self.input_buffer == "":
            self.input_buffer = raw_input()

        result = int(self.input_buffer)
        self.input_buffer = ""
        self.registers[0].store_int(result, 0)

    def getchar(self):
        if self.input_buffer == "":
            self.input_buffer = raw_input() + '\n'

        val = self.input_buffer[0]
        self.input_buffer = self.input_buffer[1:]
        self.registers[0].store_char(val, 3)

    def ADD(self, x, y):
        self.registers[x].store_int(
            self.registers[x].fetch_int(0)+self.registers[y].fetch_int(0), 0)

    def ADI(self, x, y):
        self.registers[x].store_int(
            self.registers[x].fetch_int(0)+int(y), 0)

    def SUB(self, x, y):
        self.registers[x].store_int(
            self.registers[x].fetch_int(0)-self.registers[y].fetch_int(0), 0)

    def MUL(self, x, y):
        self.registers[x].store_int(
            self.registers[x].fetch_int(0)*self.registers[y].fetch_int(0), 0)

    def DIV(self, x, y):
        self.registers[x].store_int(
            self.registers[x].fetch_int(0) / self.registers[y].fetch_int(0),
            0)

    def AND(self, x, y):
        # val > 0 is True
        if self.registers[x].fetch_int(0) and self.registers[y].fetch_int(0):
            self.registers[x].store_int(1, 0)
        else:
            self.registers[x].store_int(0, 0)

    def OR(self, x, y):
        if self.registers[x].fetch_int(0) or self.registers[y].fetch_int(0):
            self.registers[x].store_int(1, 0)
        else:
            self.registers[x].store_int(0, 0)

    def CMP(self, x, y):
        self.registers[x].store_int(
            self.registers[x].fetch_int(0)-self.registers[y].fetch_int(0), 0)

    def MOV(self, x, y):
        a = self.registers[x].memory
        b = self.registers[y].memory

        a[0] = b[0]
        a[1] = b[1]
        a[2] = b[2]
        a[3] = b[3]

    def LDA(self, x, loc):
        self.registers[x].store_int(loc, 0)

    def STR(self, x, loc):
        self.memory.store_int(self.registers[x].fetch_int(0), loc)

    def LDR(self, x, loc):
        self.registers[x].store_int(self.memory.fetch_int(loc), 0)

    def STB(self, x, loc):
        self.memory.store_char(self.registers[x].fetch_char(3), loc)

    def LDB(self, x, loc):
    	self.registers[x].memory[0] = 0
    	self.registers[x].memory[1] = 0
    	self.registers[x].memory[2] = 0
        self.registers[x].store_char(self.memory.fetch_char(loc), 3)

    def JMP(self, loc, x=None):
        self.registers[pc].store_int(loc, 0)

    def JMR(self, x, y=None):
        self.JMP(self.registers[x].fetch_int(0))

    def BNZ(self, x, loc):
        if self.registers[x].fetch_int(0) != 0:
            self.JMP(loc)

    def BGT(self, x, loc):
        if self.registers[x].fetch_int(0) > 0:
            self.JMP(loc)

    def BLT(self, x, loc):
        if self.registers[x].fetch_int(0) < 0:
            self.JMP(loc)

    def BRZ(self, x, loc):
        if self.registers[x].fetch_int(0) == 0:
            self.JMP(loc)

    def LDBI(self, x, y):
        self.LDB(x, self.registers[y].fetch_int(0))

    def STBI(self, x, y):
        self.STB(x, self.registers[y].fetch_int(0))

    def LDRI(self, x, y):
        self.LDR(x, self.registers[y].fetch_int(0))

    def STRI(self, x, y):
        self.STR(x, self.registers[y].fetch_int(0))

    def __init__(self, bytecode, pc, stack_top):
        self.memory = bytecode
        self.stack_top = stack_top
        self.stack_bottom = MEM_SIZE
        for i in range(REGISTER_COUNT):
            self.registers[i]=(MemoryManager(4))

        # Initialize state registers
        self.registers[10].store_int(pc, 0)  # PC
        self.registers[11].store_int(MEM_SIZE, 0)  # SP
        self.registers[12].store_int(stack_top, 0)  # ST
        self.registers[13].store_int(MEM_SIZE, 0)  # SB
        self.registers[14].store_int(MEM_SIZE, 0)  # FP

        self.function_map = {
            0: self.TRP,
            1: self.ADD,
            2: self.ADI,
            3: self.SUB,
            4: self.MUL,
            5: self.DIV,
            6: self.AND,
            7: self.OR,
            8: self.CMP,
            9: self.MOV,
            10: self.LDA,
            11: self.STR,
            12: self.LDR,
            13: self.STB,
            14: self.LDB,
            15: self.JMP,
            16: self.JMR,
            17: self.BNZ,
            18: self.BGT,
            19: self.BLT,
            20: self.BRZ,
            21: self.LDBI,
            22: self.STBI,
            23: self.LDRI,
            24: self.STRI
        }

    def process(self):
        # Get function code
        i = self.memory.fetch_int(self.registers[pc].fetch_int(0))
        # Determine arg 1
        _op1 = self.registers[pc].fetch_int(0) + 4
        op1 = self.memory.fetch_int(_op1)
        # Determine arg 2
        _op2 = self.registers[pc].fetch_int(0) + 8
        op2 = self.memory.fetch_int(_op2)
        # Increment PC by 1 instruction
        self.registers[pc].store_int(self.registers[pc].fetch_int(0) + 12, 0)

        # Execute
        self.function_map[i](op1, op2)


def main(*args, **kwargs):
    args = sys.argv[1:]
    if len(args) is not 1:
        print('I just want a file. A single file.')
        sys.exit(0)

    assembler = Assembler()
    assembler.read(args[0])
    assembler.first_pass()
    assembler.second_pass()
    vm = VirtualMachine(assembler.memory, assembler.code_seg, assembler.stack_top)

    while True:
        vm.process()

if __name__ == '__main__':
    main()
