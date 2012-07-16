#!/usr/bin/env python

from clang import cindex
import sys
import pdb
import ConfigParser
import yaml
import re
import os
from Cheetah.Template import Template

type_map = {
	cindex.TypeKind.VOID        : "void",
	cindex.TypeKind.BOOL        : "bool",
	cindex.TypeKind.CHAR_U      : "unsigned char",
	cindex.TypeKind.UCHAR       : "unsigned char",
	cindex.TypeKind.CHAR16      : "char",
	cindex.TypeKind.CHAR32      : "char",
	cindex.TypeKind.USHORT      : "unsigned short",
	cindex.TypeKind.UINT        : "unsigned int",
	cindex.TypeKind.ULONG       : "unsigned long",
	cindex.TypeKind.ULONGLONG   : "unsigned long long",
	cindex.TypeKind.CHAR_S      : "char",
	cindex.TypeKind.SCHAR       : "char",
	cindex.TypeKind.WCHAR       : "wchar_t",
	cindex.TypeKind.SHORT       : "short",
	cindex.TypeKind.INT         : "int",
	cindex.TypeKind.LONG        : "long",
	cindex.TypeKind.LONGLONG    : "long long",
	cindex.TypeKind.FLOAT       : "float",
	cindex.TypeKind.DOUBLE      : "double",
	cindex.TypeKind.LONGDOUBLE  : "long double",
	cindex.TypeKind.NULLPTR     : "NULL",
	cindex.TypeKind.OBJCID      : "id",
	cindex.TypeKind.OBJCCLASS   : "class",
	cindex.TypeKind.OBJCSEL     : "SEL",
	cindex.TypeKind.ENUM        : "int"
}

def native_name_from_kind(ntype):
	kind = ntype.get_canonical().kind
	if kind in type_map:
		return type_map[kind]
	elif kind == cindex.TypeKind.RECORD:
		# might be an std::string
		decl = ntype.get_declaration()
		parent = decl.semantic_parent
		if decl.spelling == "string" and parent and parent.spelling == "std":
			return "std::string"
		else:
			# print >> sys.stderr, "probably a function pointer: " + str(decl.spelling)
			return decl.spelling
	else:
		name = ntype.get_declaration().spelling
		print >> sys.stderr, "Unknown type: " + str(kind) + " " + str(name)
		return "??"
		# pdb.set_trace()

def build_namespace(cursor, namespaces = []):
	'''
	build the full namespace for a specific cursor
	'''
	if cursor:
		parent = cursor.semantic_parent
		if parent and parent.kind == cindex.CursorKind.NAMESPACE:
			namespaces += [parent.displayname]
			build_namespace(parent, namespaces)
	return "::".join(namespaces)

def namespaced_name(declaration_cursor):
	ns = build_namespace(declaration_cursor, [])
	if len(ns) > 0:
		return ns + "::" + declaration_cursor.displayname
	return declaration_cursor.displayname

class NativeType(object):
	def __init__(self, ntype):
		self.type = ntype
		self.is_pointer = False
		self.is_object = False
		self.namespaced_name = ""
		if ntype.kind == cindex.TypeKind.POINTER:
			pointee = ntype.get_pointee()
			self.is_pointer = True
			if pointee.kind == cindex.TypeKind.RECORD:
				decl = pointee.get_declaration()
				self.is_object = True
				self.name = decl.displayname
				self.namespaced_name = namespaced_name(decl)
			else:
				self.name = native_name_from_kind(pointee)
				self.namespaced_name = self.name
			self.name += "*"
			self.namespaced_name += "*"
		elif ntype.kind == cindex.TypeKind.LVALUEREFERENCE:
			pointee = ntype.get_pointee()
			if pointee.kind == cindex.TypeKind.RECORD:
				decl = pointee.get_declaration()
				self.is_object = True
				self.name = decl.displayname
				self.namespaced_name = namespaced_name(decl)
			else:
				print >> sys.stderr, "LVALUE to somthing I don't know"

		else:
			if ntype.kind == cindex.TypeKind.RECORD:
				decl = ntype.get_declaration()
				self.is_object = True
				self.name = decl.displayname
				self.namespaced_name = namespaced_name(decl)
			else:
				self.name = native_name_from_kind(ntype)
				self.namespaced_name = self.name

	def from_native(self, convert_opts):
		assert(convert_opts.has_key('generator'))
		generator = convert_opts['generator']
		name = self.name
		if self.is_object:
			if self.is_pointer:
				name = "object"
			elif not generator.config['conversions']['from_native'].has_key(name):
				name = "object"

		if generator.config['conversions']['from_native'].has_key(name):
			tpl = generator.config['conversions']['from_native'][name]
			tpl = Template(tpl, searchList=[convert_opts])
			return str(tpl).rstrip()

		return "#pragma warning NO CONVERSION FROM NATIVE FOR " + name

	def to_native(self, convert_opts):
		assert(convert_opts.has_key('generator'))
		generator = convert_opts['generator']
		name = self.name
		if self.is_object:
			if self.is_pointer:
				name = "object"
			elif not generator.config['conversions']['to_native'].has_key(name):
				name = "object"
		if generator.config['conversions']['to_native'].has_key(name):
			tpl = generator.config['conversions']['to_native'][name]
			tpl = Template(tpl, searchList=[convert_opts])
			return str(tpl).rstrip()
		return "#pragma warning NO CONVERSION TO NATIVE FOR " + name

	def to_string(self, generator):
		conversions = generator.config['conversions']
		if conversions.has_key('native_types') and conversions['native_types'].has_key(self.namespaced_name):
			return conversions['native_types'][self.namespaced_name]
		return self.namespaced_name

	def __str__(self):
		return self.namespaced_name

class NativeField(object):
	def __init__(self, cursor):
		cursor = cursor.canonical
		self.cursor = cursor
		self.name = cursor.displayname
		self.kind = cursor.type.kind
		self.location = cursor.location
		member_field_re = re.compile('m_(\w+)')
		match = member_field_re.match(self.name)
		if match:
			self.pretty_name = match.group(1)
		else:
			self.pretty_name = self.name

class NativeFunction(object):
	def __init__(self, cursor):
		self.cursor = cursor
		self.func_name = cursor.spelling
		self.signature_name = self.func_name
		self.arguments = []
		self.static = cursor.kind == cindex.CursorKind.CXX_METHOD and cursor.is_method_static()
		self.implementations = []
		self.is_constructor = False
		result = cursor.result_type
		# get the result
		if result.kind == cindex.TypeKind.LVALUEREFERENCE:
			result = result.get_pointee()
		self.ret_type = NativeType(cursor.result_type)
		# parse the arguments
		# if self.func_name == "spriteWithFile":
		# 	pdb.set_trace()
		for arg in cursor.type.argument_types():
			self.arguments += [NativeType(arg)]
		self.min_args = len(self.arguments)

	def generate_code(self, current_class=None, generator=None):
		gen = current_class.generator if current_class else generator
		config = gen.config
		tpl = Template(file=os.path.join(gen.target, "templates", "function.h"),
						searchList=[current_class, self])
		gen.head_file.write(str(tpl))
		if self.static:
			if config['definitions'].has_key('sfunction'):
				tpl = Template(config['definitions']['sfunction'],
									 searchList=[current_class, self])
				self.signature_name = str(tpl)
			tpl = Template(file=os.path.join(gen.target, "templates", "sfunction.c"),
							searchList=[current_class, self])
		else:
			if not self.is_constructor:
				if config['definitions'].has_key('ifunction'):
					tpl = Template(config['definitions']['ifunction'],
									searchList=[current_class, self])
					self.signature_name = str(tpl)
			else:
				if config['definitions'].has_key('constructor'):
					tpl = Template(config['definitions']['constructor'],
									searchList=[current_class, self])
					self.signature_name = str(tpl)
			tpl = Template(file=os.path.join(gen.target, "templates", "ifunction.c"),
							searchList=[current_class, self])
		gen.impl_file.write(str(tpl))

class NativeOverloadedFunction(object):
	def __init__(self, func_array):
		self.implementations = func_array
		self.func_name = func_array[0].func_name
		self.signature_name = self.func_name
		self.min_args = 100
		self.is_constructor = False
		for m in func_array:
			self.min_args = min(self.min_args, m.min_args)

	def append(self, func):
		self.min_args = min(self.min_args, func.min_args)
		self.implementations += [func]

	def generate_code(self, current_class=None):
		gen = current_class.generator
		config = gen.config
		static = self.implementations[0].static
		tpl = Template(file=os.path.join(gen.target, "templates", "function.h"),
						searchList=[current_class, self])
		gen.head_file.write(str(tpl))
		if static:
			if config['definitions'].has_key('sfunction'):
				tpl = Template(config['definitions']['sfunction'],
								searchList=[current_class, self])
				self.signature_name = str(tpl)
			tpl = Template(file=os.path.join(gen.target, "templates", "sfunction_overloaded.c"),
							searchList=[current_class, self])
		else:
			if not self.is_constructor:
				if config['definitions'].has_key('ifunction'):
					tpl = Template(config['definitions']['ifunction'],
									searchList=[current_class, self])
					self.signature_name = str(tpl)
			else:
				if config['definitions'].has_key('constructor'):
					tpl = Template(config['definitions']['constructor'],
									searchList=[current_class, self])
					self.signature_name = str(tpl)
			tpl = Template(file=os.path.join(gen.target, "templates", "ifunction_overloaded.c"),
							searchList=[current_class, self])
		gen.impl_file.write(str(tpl))


class NativeClass(object):
	def __init__(self, cursor, generator):
		# the cursor to the implementation
		self.cursor = cursor
		self.class_name = cursor.displayname
		self.namespaced_class_name = self.class_name
		self.parents = []
		self.fields = []
		self.methods = {}
		self.static_methods = {}
		self.generator = generator
		if generator.remove_prefix:
			self.target_class_name = re.sub(generator.remove_prefix, '', self.class_name)
		else:
			self.target_class_name = self.class_name
		self.namespaced_class_name = namespaced_name(cursor)
		self.parse()

	def parse(self):
		'''
		parse the current cursor, getting all the necesary information
		'''
		self._deep_iterate(self.cursor)

	def methods_clean(self):
		'''
		clean list of methods (without the ones that should be skipped)
		'''
		ret = []
		for name, impl in self.methods.iteritems():
			should_skip = False
			if name == 'constructor':
				should_skip = True
			else:
				if self.generator.should_skip(self.class_name, name):
					should_skip = True
			if not should_skip:
				ret += [{"name": name, "impl": impl}]
		return ret

	def static_methods_clean(self):
		'''
		clean list of static methods (without the ones that should be skipped)
		'''
		ret = []
		for name, impl in self.static_methods.iteritems():
			should_skip = self.generator.should_skip(self.class_name, name)
			if not should_skip:
				ret += [{"name": name, "impl": impl}]
		return ret

	def generate_code(self):
		'''
		actually generate the code. it uses the current target templates/rules in order to
		generate the right code
		'''
		config = self.generator.config
		prelude_h = Template(file=os.path.join(self.generator.target, "templates", "prelude.h"),
							 searchList=[{"current_class": self}])
		prelude_c = Template(file=os.path.join(self.generator.target, "templates", "prelude.c"),
							 searchList=[{"current_class": self}])
		self.generator.head_file.write(str(prelude_h))
		self.generator.impl_file.write(str(prelude_c))
		for m in self.methods_clean():
			m['impl'].generate_code(self)
		for m in self.static_methods_clean():
			m['impl'].generate_code(self)
		# generate register section
		register = Template(file=os.path.join(self.generator.target, "templates", "register.c"),
							searchList=[{"current_class": self}])
		self.generator.impl_file.write(str(register))

	def _deep_iterate(self, cursor=None):
		for node in cursor.get_children():
			if self._process_node(node):
				self._deep_iterate(node)

	def _process_node(self, cursor):
		'''
		process the node, depending on the type. If returns true, then it will perform a deep
		iteration on its children. Otherwise it will continue with its siblings (if any)

		@param: cursor the cursor to analyze
		'''
		if cursor.kind == cindex.CursorKind.CXX_BASE_SPECIFIER and not self.class_name in self.generator.base_objects:
			parent = cursor.get_definition()
			if parent:
				if not self.generator.generated_classes.has_key(parent.displayname):
					parent = NativeClass(parent, self.generator)
					self.generator.generated_classes[parent.class_name] = parent
				else:
					parent = self.generator.generated_classes[parent.displayname]
				self.parents += [parent]
		elif cursor.kind == cindex.CursorKind.FIELD_DECL:
			self.fields += [NativeField(cursor)]
		elif cursor.kind == cindex.CursorKind.CXX_METHOD:
			# skip if variadic
			if not cursor.type.is_function_variadic():
				m = NativeFunction(cursor)
				if m.static:
					if not self.static_methods.has_key(m.func_name):
						self.static_methods[m.func_name] = m
					else:
						previous_m = self.static_methods[m.func_name]
						if isinstance(previous_m, NativeOverloadedFunction):
							previous_m.append(m)
						else:
							self.static_methods[m.func_name] = NativeOverloadedFunction([m, previous_m])
				else:
					if not self.methods.has_key(m.func_name):
						self.methods[m.func_name] = m
					else:
						previous_m = self.methods[m.func_name]
						if isinstance(previous_m, NativeOverloadedFunction):
							previous_m.append(m)
						else:
							self.methods[m.func_name] = NativeOverloadedFunction([m, previous_m])
		elif cursor.kind == cindex.CursorKind.CONSTRUCTOR and not self.class_name in self.generator.abstract_classes:
			m = NativeFunction(cursor)
			m.is_constructor = True
			if not self.methods.has_key('constructor'):
				self.methods['constructor'] = m
			else:
				previous_m = self.methods['constructor']
				if isinstance(previous_m, NativeOverloadedFunction):
					previous_m.append(m)
				else:
					m = NativeOverloadedFunction([m, previous_m])
					m.is_constructor = True
					self.methods['constructor'] = m
		# else:
			# print >> sys.stderr, "unknown cursor: %s - %s" % (cursor.kind, cursor.displayname)

class Generator(object):
	def __init__(self, opts):
		self.index = cindex.Index.create()
		self.outdir = opts['outdir']
		self.prefix = opts['prefix']
		self.headers = opts['headers'].split(' ')
		self.classes = opts['classes']
		self.base_objects = opts['base_objects'].split(' ')
		self.abstract_classes = opts['abstract_classes'].split(' ')
		self.clang_args = opts['clang_args']
		self.target = os.path.join("targets", opts['target'])
		self.remove_prefix = opts['remove_prefix']
		self.target_ns = opts['target_ns']
		self.impl_file = None
		self.head_file = None
		self.skip_classes = {}
		self.generated_classes = {}
		if opts['skip']:
			list_of_skips = re.split(",\n?", opts['skip'])
			for skip in list_of_skips:
				class_name, methods = skip.split("::")
				self.skip_classes[class_name] = []
				match = re.match("\[([^]]+)\]", methods)
				if match:
					self.skip_classes[class_name] = match.group(1).split(" ")
				else:
					raise Exception("invalid list of skip methods")

	def should_skip(self, class_name, method_name):
		if self.skip_classes.has_key(class_name):
			return method_name in self.skip_classes[class_name]
		return False

	def sorted_classes(self):
		'''
		sorted classes in order of inheritance
		'''
		sorted_list = []
		for class_name in self.classes:
			nclass = self.generated_classes[class_name]
			sorted_list += self._sorted_parents(nclass)
		# remove dupes from the list
		no_dupes = []
		[no_dupes.append(i) for i in sorted_list if not no_dupes.count(i)]
		return no_dupes

	def _sorted_parents(self, nclass):
		'''
		returns the sorted list of parents for a native class
		'''
		sorted_parents = []
		for p in nclass.parents:
			if p.class_name in self.classes:
				sorted_parents += self._sorted_parents(p)
		if nclass.class_name in self.classes:
			sorted_parents += [nclass.class_name]
		return sorted_parents

	def generate_code(self):
		# must read the yaml file first
		stream = file(os.path.join(self.target, "conversions.yaml"), "r")
		data = yaml.load(stream)
		self.config = data
		implfilepath = os.path.join(self.outdir, self.prefix + ".cpp")
		headfilepath = os.path.join(self.outdir, self.prefix + ".hpp")
		self.impl_file = open(implfilepath, "w+")
		self.head_file = open(headfilepath, "w+")

		layout_h = Template(file=os.path.join(self.target, "templates", "layout_head.h"),
							 searchList=[self])
		layout_c = Template(file=os.path.join(self.target, "templates", "layout_head.c"),
							 searchList=[self])
		self.head_file.write(str(layout_h))
		self.impl_file.write(str(layout_c))

		self._parse_headers()

		layout_h = Template(file=os.path.join(self.target, "templates", "layout_foot.h"),
							 searchList=[self])
		layout_c = Template(file=os.path.join(self.target, "templates", "layout_foot.c"),
							 searchList=[self])
		self.head_file.write(str(layout_h))
		self.impl_file.write(str(layout_c))

		self.impl_file.close()
		self.head_file.close()

	def _parse_headers(self):
		for header in self.headers:
			tu = self.index.parse(header, self.clang_args)
			if len(tu.diagnostics) > 0:
				is_fatal = False
				for d in tu.diagnostics:
					if d.severity >= cindex.Diagnostic.Error:
						is_fatal = True
					print(d.category_name + ": " + str(d.location))
					print("  " + d.spelling)
				if is_fatal:
					print("*** Found errors - can not continue")
					return
			self._deep_iterate(tu.cursor)

	def _deep_iterate(self, cursor, depth=0):
		# get the canonical type
		is_class = False
		if cursor.kind == cindex.CursorKind.CLASS_DECL:
			if cursor == cursor.type.get_declaration() and cursor.displayname in self.classes:
				if not self.generated_classes.has_key(cursor.displayname):
					nclass = NativeClass(cursor, self)
					nclass.generate_code()
					self.generated_classes[cursor.displayname] = nclass
				return

		for node in cursor.get_children():
			# print("%s %s - %s" % (">" * depth, node.displayname, node.kind))
			self._deep_iterate(node, depth+1)

def main():
	from optparse import OptionParser, OptionGroup

	parser = OptionParser("usage: %prog [options] {configfile}")
	parser.add_option("-s", action="store", type="string", dest="section",
						help="sets a specific section to be converted")
	parser.add_option("-t", action="store", type="string", dest="target",
						help="specifies the target vm. Will search for TARGET.yaml")
	parser.add_option("-o", action="store", type="string", dest="outdir",
						help="specifies the output directory for generated C++ code")

	(opts, args) = parser.parse_args()

	if len(args) == 0:
		parser.error('invalid number of arguments')

	config = ConfigParser.SafeConfigParser()
	config.read(args[0])

	if (0 == len(config.sections())):
		raise Exception("No sections defined in config file")

	sections = []
	if opts.section:
		if (opts.section in config.sections()):
			sections = []
			sections.append(opts.section)
		else:
			raise Exception("Section not found in config file")
	else:
		print("processing all sections")
		sections = config.sections()

	# find available targets
	targets = []
	if (os.path.isdir("targets")):
		targets = [entry for entry in os.listdir("targets")
				   if (os.path.isdir(os.path.join("targets", entry)))]
		if 0 == len(targets):
			raise Exception("No targets defined")

	if opts.target:
		if (opts.target in targets):
			targets = []
			targets.append(opts.target)

	if opts.outdir:
		outdir = opts.outdir
	else:
		outdir = "gen"
	if not os.path.exists(outdir):
		os.makedirs(outdir)

	for t in targets:
		print "\n.... Generating bindings for target", t
		for s in sections:
			print "\n.... .... Processing section", s, "\n"
			gen_opts = {
				'prefix': config.get(s, 'prefix'),
				'headers': config.get(s, 'headers'),
				'classes': config.get(s, 'classes').split(' '),
				'clang_args': (config.get(s, 'extra_arguments') or "").split(" "),
				'target': t,
				'outdir': outdir,
				'remove_prefix': config.get(s, 'remove_prefix'),
				'target_ns': config.get(s, 'target_namespace'),
				'base_objects': config.get(s, 'base_objects'),
				'abstract_classes': config.get(s, 'abstract_classes'),
				'skip': config.get(s, 'skip')
				}
			generator = Generator(gen_opts)
			generator.generate_code()

if __name__ == '__main__':
	main()
