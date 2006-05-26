#!/usr/bin/env python
# Encoding: iso-8859-1 tabs=4:tabs
# vim: ts=4 noet
# -----------------------------------------------------------------------------
# Project           :   Archipel           <http://sofware.type-z.org/archipel>
# Module            :   Change tracking
# -----------------------------------------------------------------------------
# Author            :   Sebastien Pierre (SPE)           <sebastien@type-z.org>
# License           :   BSD License (revised)
# -----------------------------------------------------------------------------
# Creation date     :   09-Dec-2003
# Last mod.         :   17-Jan-2006
# History           :
#                       17-Jan-2006 Some API refactoring (compatibility broken) (SPE)
#                       19-Dec-2004 Skip list for attributes in signature (SPE)
#                       03-Dec-2004 Symlinks are skipped (SPE)
#                       01-Jun-2004 Can delete nodes from changes (SPE)
#                       25-May-2004 Added `getAbsoluteLocation' (SPE)
#                       15-May-2004 Renamed Delta to Change (SPE)
#                       28-Apr-2004 Added tracking attributes (SPE)
#                       27-Apr-2004 Recorded state snapshot time (SPE)
#                       05-Apr-2004 Renamed Node to NodeState (SPE)
#                       21-Jan-2004 Signature is now split into data and
#                       attributes signatures. (SPE)
#                       09-Jan-2004 Updated XML serialization. (SPE)
#                       05-Jan-2004 Prefixed with FileSystem or suffixed with
#                       NodeState. Added draft XML parser and serialize, updated API
#                       to enable parser/serializer implementation (SPE)
#                       30-Dec-2003 Implemented directory, folder and state.
#                       Added attributes-information support to nodes, added
#                       ancestor guessing function. (SPE)
#                       09-Dec-2003 First implementation (SPE)
#
# Bugs              :
#                       - When a directory contains a symbolic link that creates
#                         a circle (eg /a/b points to /a), the trakcking dies.
#                         I should add a "sanity check" before tracking changes
# To do             :
#                       - Optimize directory update
#
# Notes             :
#                       - NodeStates SHOULD not be created directly, because they
#                       MUST be cached (signature and location) in their
#                       containing state to be processable by the change
#                       tracker.

import os, sha, stat, sys, time, xml.dom

# Error messages

BAD_DOCUMENT_ELEMENT = "Bad document element"
NO_LOCATION = "No `location' attribute."
UNKNOWN_ELEMENT = "Unknown element %s"

#------------------------------------------------------------------------------
#
#  File system node
#
#------------------------------------------------------------------------------

FILE_SYSTEM_ATTRIBUTES = (
	"Size", "Creation", "Modification", "Owner", "Group", "Permissions",
)


class NodeState:
	"""The abstract class for representing the state of filesystem files
	and directories."""

	ADDED    = "+"
	REMOVED  = "-"
	MODIFIED = "m"
	
	def __init__( self, state, location, usesSignature=True ):
		"""Creates a file system node with the given location. The location
		is relative to the state root. The usesSignature parameter allows to
		specify wether the node should use a signature or not. Large file nodes may take
		too long to compute their signature, in which case this attributes
		comes in handy.

		The `update' method should be called to initilize the signature and
		attributes attributes from the local filesystem, but this implies that the
		nodes exists on the file system. Otherwise the `_attributes' and `_contentSignature'
		attributes can be set by hand."""
		self._parent = None
		self._attributes = {}
		self._tags = {}
		self._contentSignature = None
		self._attributesSignature = None
		self._usesSignature = usesSignature
		self._belongsToState( state )
		self.location( location )

	def isDirectory( self ):
		"""Tells wether the node is a directory or not."""
		return False
	
	def hasChildren( self ):
		return 0
	
	def children( self ):
		return ()

	def doOnParents(self, function):
		if self._parent:
			function(self._parent)
			self._parent.doOnParents(function)
	
	def usesSignature( self ):
		"""Tells wether this node should copmute its SHA-1 signature when updated."""
		return self._usesSignature
	
	def _appendToWalkPath( self, walkPath ):
		"""Appends this node to the given walk path. This allows to iterate
		nodes using the given `walkPath', which is a list."""
		walkPath.append(self)

	def _belongsToState( self, state ):
		"""Tells that this node belongs to the given state. This clears the node
		cache."""
		self._state = state
		self._cached = False

	def _setParent( self, nodeState ):
		"""Sets the parent NodeState for this node."""
		self._parent = nodeState

	# Tagging___________________________________________________________________

	def tag(self, name=None, **tags):
		if name:
			return self._tags.get(name)
		else:
			for key in tags:
				self._tags[key] = tags[key]
			return True

	# Caching__________________________________________________________________


	def isCached( self, value=None ):
		"""Tells wether the node is cached, or not."""
		if value == None:
			return self._cached
		else:
			self._iscached = value

	def location( self, location=None ):
		"""Sets the location that this node represents, relatively to the state
		root"""
		if location == None:
			return self._attributes["Location"]
		else:
			location = os.path.normpath(location)
			self._attributes["Location"] = location

	def name(self):
		return os.path.basename(self.location())
		
	def getAbsoluteLocation( self ):
		"""Returns the node location, which implies that the location has been
		assigned a state."""
		assert self._state != None
		return self._state.getAbsoluteLocation(self.location())

	def exists( self ):
		"""Returns true if the node exists on the local filesystem"""
		return os.path.exists( self.getAbsoluteLocation() )

	def update( self, signatureFilter=lambda x:True ):
		"""Creates the node by making the proper initilisation. The node MUST
		be available on the local filesystem when this method is run."""
		# Links may point to unexisting locations
		assert os.path.islink(self.getAbsoluteLocation()) or self.exists()
		self._updateAttributes()
		self._updateSignature()
		self._state.cacheNodeState(self)

	def _updateAttributes( self ):
		"""Gathers the attributes related to this file system node."""
		path = self.getAbsoluteLocation()
		assert self.exists()
		stat_info = map(lambda x:str(x), os.stat(path))
		self._attributes["Size"] = stat_info[stat.ST_SIZE]
		self._attributes["Creation"] = stat_info[stat.ST_CTIME]
		self._attributes["Modification"] = stat_info[stat.ST_MTIME]
		self._attributes["Owner"] = stat_info[stat.ST_UID]
		self._attributes["Group"] = stat_info[stat.ST_GID]
		self._attributes["Permissions"] = stat_info[stat.ST_MODE]

	def getAttribute( self, info ):
		"""Returns the attributes information with the given name"""
		return self._attributes[info]

	def getAttributes( self ):
		"""Returns the attributes of this node."""
		return self._attributes

	def _attributeInSignature( self, attributeName ):
		"""Tells wether the given attribute name should be used in the computation
		of the signature."""
		if attributeName not in ( "Creation" ):
			return True
		else:
			return False

	def _updateSignature( self ):
		"""Creates the signature of this file system node."""

		# The content signature is up to concrete subclasses, so we only
		# set it to None (which is its default value)
		self._contentSignature = None

		# Updates the attributes signature
		items = self._attributes.items()
		items.sort()
		signature = sha.new()
		for key, value in items:
			# Creation attribute does not appear in the attributes signature
			if self._attributeInSignature(key):
				signature.update(str(key)+str(value))
		self._attributesSignature = signature.hexdigest()

	def getContentSignature( self ):
		if self._contentSignature == None: self._updateSignature()
		return self._contentSignature

	def getAttributesSignature( self ):
		"""Returns the signature of the attributes. Attributes listed in
		ATTRIBUTES_NOT_IN_SIGNATURE are not taken into account in the
		computation of the node signature."""
		if self._attributesSignature == None: self._updateSignature()
		return self._attributesSignature

	def getSignature( self ):
		"""Returns the concatenation of the content signature and the
		attributes signature, separated by a dash."""
		return str(self.getContentSignature())+"-"+str(self.getAttributesSignature())
	
	def __repr__(self):
		return os.path.basename(self.location()) + " " + repr(self._tags)
		
#------------------------------------------------------------------------------
#
#  DirectoryNodeState
#
#------------------------------------------------------------------------------

class DirectoryNodeState(NodeState):
	"""A node representing a directory on the filesystem"""

	def __init__( self, state, location ):
		"""Creates a new directory node.

		Same operations as the file system node."""
		# The list of child nodes
		self._children = []
		NodeState.__init__(self, state, location )

	def isDirectory( self ):
		"""Returns True."""
		return True
	
	def hasChildren( self ):
		return len(self._children)
	
	def children( self ):
		return self._children
	
	def _belongsToState( self, state ):
		"""Sets the given state as this node state. This invalidates makes the
		node uncached."""
		NodeState._belongsToState(self, state)
		for child in self.getChildren(): child._belongsToState(state)

	def update( self, nodeSignatureFilter=lambda x:True ):
		"""Updates the given directory node signature and attributes-information. The
		directory node location MUST exist.

		The nodeSignatureFilter allows to filter each node and decided wether its signature
		should be computed or not. By default, every node has its signature computed.

		WARNING: Updating a directory nodes updates its children list according
		to the local file system, so new nodes are always created for new
		directories and files."""
		# We ensure that the directory exists
		assert self.exists()
		# We retrieve an order list of the directory content
		content=os.listdir(self.getAbsoluteLocation())
		self._children = []
		# We create new nodes for each content
		for element_loc in content:
			element_loc = os.path.join( self.location(), element_loc )
			abs_element_loc = self._state.getAbsoluteLocation(element_loc)
			# Skips symlinks
			if os.path.islink( abs_element_loc):
				continue
			elif os.path.isdir( abs_element_loc ):
				node = DirectoryNodeState( self._state, element_loc )
				node.update(nodeSignatureFilter)
			else:
				if nodeSignatureFilter(abs_element_loc):
					node = FileNodeState( self._state, element_loc, True )
				else:
					node = FileNodeState( self._state, element_loc, False )
				node.update()
			if node: self.appendChild(node)
		# This is VERY IMPORTANT : we ensure that the children are canonicaly
		# sorted
		self._children.sort(lambda x,y: cmp(x.location(), y.location()))
		# We can only update the node after children were added, see
		# _updateSignature
		NodeState.update(self)

	def _appendToWalkPath( self, walkPath ):
		"""Appends this node to the given walk path. This allows to iterate
		nodes using the given `walkPath', which is a list.

		Directory node is appended first, then children are appended in
		alphabetical order."""
		NodeState._appendToWalkPath(self, walkPath)
		for child in self._children: child._appendToWalkPath(walkPath)

	def walkChildren( self, function, context=None ):
		"""Applies the given function to every child of this node."""
		for child in self._children:
			if context != None:
				function(child, context)
			else:
				function(child)
			if child.hasChildren():
				child.walkChildren(function, context)

	def getChildren( self, types = None ):
		"""Returns the children of this directory. The optional `types' list
		enumerates the classes of the the returned children, acting as a type
		filter. By default, types are DirectoryNodeState and FileNodeState."""
		if types == None: types = ( DirectoryNodeState, FileNodeState )
		# Returns only elements of the listed types
		def typefilter(x):
			for atype in types:
				if isinstance(x,atype): return True
			return False
		# We execute the filter
		return filter( typefilter, self._children )

	def appendChild( self, child ):
		"""Appends a child node to this directory. The list of children is
		automatically maintained as sorted."""
		self._children.append(child)
		child._setParent(self)
		# We make sure the list of children is sorted.
		self._children.sort()

	def _attributeInSignature( self, attributeName ):
		"""Tells wether the given attribute name should be used in the computation
		of the signature."""
		if attributeName not in ( "Creation", "Modification" ):
			return True
		else:
			return False

	def _updateSignature( self ):
		"""A directory signature is the signature of the string composed of the
		names of all of its elements."""
		NodeState._updateSignature(self)
		self._contentSignature = sha.new()
		for child in self.getChildren():
			self._contentSignature.update(os.path.basename(child.location()))
		self._contentSignature = self._contentSignature.hexdigest()

	def __repr__(self):
		def indent(text, value = "  ", firstLine=False):
			res = ""
			for line in text.split("\n"):
					if firstLine:
						res += value + line + "\n"
					else:
						firstLine = True
						res += line + "\n"
			return res
		name = "[ ] " + NodeState.__repr__(self) + "\n"
		for child in self._children:
				name += " +-- " + indent(repr(child), "     ", False)		
		return name
	
#------------------------------------------------------------------------------
#
#  FileNodeState
#
#------------------------------------------------------------------------------

class FileNodeState(NodeState):
	"""A node representing a file on the filesystem."""

	def isDirectory( self ):
		"""Returns False."""
		return False

	def getData( self ):
		"""Returns the data contained in this file as a string."""
		fd = None
		fd = open(self.getAbsoluteLocation(), "r")
		assert fd!=None
		data = fd.read()
		fd.close()
		return data

	def _updateSignature( self ):
		"""A file signature is the signature of its content."""
		NodeState._updateSignature(self)
		# We only compute the content signature if the node is said to. This
		# allows to perform quick changes detection when large files are
		# involved.
		if self.usesSignature():
			self._contentSignature = sha.new(self.getData())
			self._contentSignature = self._contentSignature.hexdigest()

#------------------------------------------------------------------------------
#
#  Ancestor guessing
#
#------------------------------------------------------------------------------

def guessNodeStateAncestors( node, nodes ):
	"""Returns an order list of (percentage, nodes) indicating the
	probability for each node to be an ancestor of the current node.

	You should look at the source code for more information on how the
	percentage is avaluated."""
	# TODO: Make more test and try to explain why this should work. I think
	# this should be tuned by usage.
	assert len(nodes)>0
	# Computes the difference between the given node and the current node
	# attributes information value
	def difference( node, info ):
		return abs(int(node.getAttribute(info)) - int(node.getAttribute(info)))
	# Initialises the maxima table for the given attributes info
	maxima = {
		"Creation":difference(nodes[0], "Creation"),
		"Size":difference(nodes[0], "Size")
	}
	# We get the maxima for each attributes info
	for attributes in ("Creation", "Size"):
		for node in nodes:
			maxima[attributes] = max(maxima[attributes], difference(node, attributes))
	# We calculate the possible ancestry rate
	result = []
	for node in nodes:
		node_rate = 0.0
		# Same class, rate 40%
		if node.__class__ == node.__class__:
			node_rate += 0.40
		# Creation rate, up to 25%
		creation_rate = 0.25 * ( 1 - float(difference(node, "Creation")) /
			maxima["Creation"] )
		# Divided by two if rated node creation date is > to current node
		# creation date
		if node.getAttribute("Creation") > \
		   node.getAttribute("Creation"):
			creation_rate = creation_rate / 2.0
		node_rate += creation_rate
		# If modification date is < to current modification date, add 15%
		if node.getAttribute("Modification") < \
		   node.getAttribute("Modification"):
			node_rate += 0.15
		# Size rate, up to 10%
		node_rate += 0.10 * ( 1 - float(difference(node, "Size")) /
			maxima["Size"] )
		# If owner is the same then add 3%
		if node.getAttribute("Owner") ==\
		   node.getAttribute("Owner"):
			node_rate += 0.03
		# If group is the same then add 3%
		if node.getAttribute("Group") ==\
		   node.getAttribute("Group"):
			node_rate += 0.03
		# If permissions are the same then add 3%
		if node.getAttribute("Permissions") ==\
		   node.getAttribute("Permissions"):
			node_rate += 0.03
		result.append((node_rate, node))
	result.sort(lambda x,y: cmp(x[0], y[0]))
	return result

#------------------------------------------------------------------------------
#
#  File system state
#
#------------------------------------------------------------------------------

class State:
	"""A state object reflects the state of a particular file system location
	by creating node objects (NodeStates) that represent the file system. 
	These nodes can be 	queried by location and signature."""

	def __init__( self, rootLocation, rootNodeState=None, populate=False ):
		"""Creates a new state with the given location as the root. If the populate
		variable is set to True, then the state is populated with the data gathered
		from the fielsystem.

		Note that the given rootNodeState is NOT UPDATED automatically, because
		it may not exist on the local filesystem.

		By default, no root node is created, you can create one with the
		'populate' method."""
		# Signatures and locations are used by the change tracking system
		# Signatures is a map with signatures as key and a list of file system
		# nodes as values.
		self._contentSignatures = {}
		# Locations is a map with location as keys and file system nodes as
		# values.
		self._locations = {}
		self._rootNodeState = None
		if rootLocation: self.location(os.path.abspath(rootLocation))
		else: self.location(None)
		self.root(rootNodeState)
		if populate:
				self.populate()

	def populate( self, nodeSignatureFilter=lambda x:True):
		"""Creates the root node for this state. This node will be
		automatically updated and cached.

		The nodeSignatureFilter is a predicate which tells if a node at the
		given location should compute its signature or not.
		"""
		rootNodeState = DirectoryNodeState(self, "")
		rootNodeState.update(nodeSignatureFilter)
		self._creationTime = time.localtime()
		self.root(rootNodeState)

	def root( self, node=None ):
		"""Returns this state root node."""
		if node != None: self._rootNodeState = node
		else:	return self._rootNodeState

	def getCreationTime( self ):
		"""Returns the time at which this state was created"""
		return self._creationTime

	def location( self, path=None ):
		"""Returns the absolute location of this state in the local
		filesystem."""
		if path == None:
			return self._rootLocation
		else:
			self._rootLocation = path

	def getAbsoluteLocation( self, location ):
		"""Returns the absolute location of the given relative location"""
		return os.path.normpath(self.location() + os.sep + location)

	def cacheNodeState( self, node ):
		"""Caches a node information in this state. This registers the node
		signature and location so that it can be processed by the change
		tracking."""
		self._locations[node.location()] = node
		result = None
		# We make sure that the singature exists
		if node.usesSignature():
			try:
				result = self._contentSignatures[node.getContentSignature()]
			except:
				result = []
				self._contentSignatures[node.getContentSignature()] = result
			# And we append the node
			result.append(node)
		node.isCached(True)
		return node

	def cacheNodeStates( self ):
		assert self.root()
		for node in self.root().walkNodeStates():
			if not node.isCached():
				self.cacheNodeState(node)

	def nodesWithContentSignature( self, signature ):
		"""Returns a list of nodes with the given content signature. The node
		may not exist, in which case None is returned."""
		try:
			return self._contentSignatures[signature]
		except:
			return ()

	def nodeWithLocation( self, location ):
		"""Returns the node with the given location. The node may not exist, in
		which case None is returned."""
		try:
			return self._locations[location]
		except:
			return None

	def nodesByLocation( self ):
		return self._locations

	def nodesByContentSignature( self ):
		return self._contentSignatures

	def save( self, filePath ):
		"""Saves the state to the given file as an XML document."""
		document = StateSerializer().serializeState(self)
		fd = open(filePath, "w")
		fd.write(document.toxml())
		fd.close()

	def load( self, filePath ):
		"""Creates a new state from the given state XML document."""
		return StateParser().parseState(xml.dom.parse(filePath))

	def __repr__(self):
		return repr(self.root())
	
#------------------------------------------------------------------------------
#
#  Change tracking
#
#------------------------------------------------------------------------------

def sets( firstSet, secondSet, objectAccessor=lambda x:x ):
	"""
	Returns elements that are unique to first and second set, then elements
	that are common to both.

	Returns the following sets:

		- elements only in first set
		- elements only in second set
		- elements common to both sets

	The objectAccessor operation is used on each object of the set to access
	the element that will be used as a comparison basis. By default, it is the
	element itself."""

	# We precompute the maps
	set_first_acc  = map(objectAccessor, firstSet)
	set_second_acc = map(objectAccessor, secondSet)

	# Declare the filtering predicates
	# First set elements not in second set
	def first_only(x): return objectAccessor(x) not in set_second_acc
	# Second set elements not in first set
	def second_only(x): return objectAccessor(x) not in set_first_acc
	# First sets elements in second set == second set elts in first set
	def common(x): return objectAccessor(x) in set_second_acc

	# Compute the result
	return	filter(first_only, firstSet),\
			filter(second_only, secondSet),\
			filter(common, firstSet)

class Change:
	"""A change represents differences between two states."""

	def __init__ ( self, newState, previousState ):
		# created+copied+moved = total of nodes only in new state
		self._created   = [] # Only in NEW
		self._copied    = [] # Only in NEW
		self._moved     = [] # Only in NEW
		# removed = total of nodes only in old state
		self._removed   = [] # Only in OLD
		# changed + unchanged = total of nodes in both STATES
		self._modified   = []
		self._unmodified = []
		# We do not count untracked, because this is a superset
		self._all =  [
			self._created,
			self._copied,
			self._moved,
			self._removed,
			self._modified,
			self._unmodified
		]
		self.newState      = newState
		self.previousState = previousState

	def anyChanges( self ):
		"""Tells wether there were any changes"""
		for group in self._all[:-1]:
			if group: return True
		return False

	def removeLocation( self, location ):
		"""Removes the nodes that start with the given location from this
		change set."""
		if location == None: return
		for set in self._all:
			i = 0
			# We cannot iterate on the array, because we may remove the
			# iterated value, which seems to fuck up the iteration
			while i < len(set):
				node = set[i]
				if node.location().find(location) == 0:
					set.pop(i)
				else:
					i += 1

	def getOnlyInNewState( self ):
		res = []
		res.extend(self._created)
		res.extend(self._copied)
		res.extend(self._moved)
		return res

	def getOnlyInOldState( self ):
		return self._removed

	def getOnlyInBothStates( self ):
		res = []
		res.extend(self._modified)
		res.extend(self._unmodified)

	def getCreated( self ):
		return self._created

	def getCopied( self ):
		return self._copied

	def getRemoved( self ):
		return self._removed

	def getMoved( self ):
		return self._moved

	def getModified( self ):
		return self._modified

	def getUnmodified( self ):
		return self._unmodified

	def _filterAll( self, f ):
		result = []
		for set in self._all: result.extend(filter(f,set))
		return result

	def count( self ):
		"""Returns the number of elements in this change."""
		# FIXME: This is false !
		count = 0
		for set in self._all: count += len(set)
		return count

class Tracker:
	"""Creates a change object that characterises the difference between  the
	two states."""

	def detectChanges( self, newState, previousState ):
		"""Detects the changes between the new state and the previous state. This
		returns a Change object representing all changes."""

		changes = Change(newState, previousState)

		# We look for new nodes, nodes that are only in the previous location,
		# and nodes that are still there
		new_locations, prev_locations, same_locations = sets(
			newState.nodesByLocation().items(),
			previousState.nodesByLocation().items(),
			lambda x:x[0]
		)

		# TODO: This should be improved with copied and moved files, but this
		# would require a GUI

		# TODO: changes._all, ._new and ._old are not space efficient

		for location, node in new_locations:
			self.onCreated(node)
			changes._created.append(node)

		for location, node in prev_locations:
			self.onRemoved(node)
			changes._removed.append(node)

		for location, node in same_locations:
			previous_node = previousState.nodeWithLocation(location)
			if previous_node.getSignature() != node.getSignature():
				changes._modified.append(node)
				self.onModified(previous_node, node)
			else:
				changes._unmodified.append(node)
				self.onUnmodified(previous_node, node)

		# We make sure that we classified every node of the state
		assert len(new_locations) + len(prev_locations) + len(same_locations)\
		== changes.count()

		return changes
	
	def onCreated( self, node ):
		"""Handler called when a node was created, ie. it is present in the new
		state and not in the old one."""
		node.tag(event=NodeState.ADDED)
		node.doOnParents(lambda x:x.tag("event") == None and x.tag(event=NodeState.MODIFIED))
	
	def onModified(self, newNode, oldNode):
		"""Handler called when a node was modified, ie. it is not the same in
		the new and in the old state."""
		newNode.tag(event=NodeState.MODIFIED)
		oldNode.tag(event=NodeState.MODIFIED)

	def onUnmodified(self, newNode, oldNode):
		newNode.tag(event=None)
		oldNode.tag(event=None)

	def onRemoved(self, node):
		"""Handler called when a node was removed, ie. it is not the in
		the new state but is in the old state."""
		node.tag(event=NodeState.REMOVED)

#------------------------------------------------------------------------------
#
#  XML Serialisation and deserialisation
#
#------------------------------------------------------------------------------

class StateParser:
	"""Parses a file system file from an XML node."""

	def parseState( self, node ):
		"""Parses the given XML node."""
		# FIXME: Handle errors
		if node.documentElement.localName != "State":
			return self.error(BAD_DOCUMENT_ELEMENT)
		location = node.documentElement.getAttributeNS(None, "location")
		state = State(location)

		# We look for a recognised child node
		root_node = None
		for childNode in node.documentElement.childNodes:
			root_node = self.parseChildNodeState(state, childNode)
			if root_node:  break
		# And set it as the root node
		state.root(root_node)
		state.cacheNodeStates()
		return state

	def parseChildNodeState( self, state, childNode ):
		if childNode.localName == "Directory":
			return self.parseDirectoryNodeState(state, childNode)
		elif childNode.localName == "File":
			return self.parseFileNodeState(state, childNode)
		elif childNode.localName in ("Attributes", "signature"):
			return None
		else:
			self.warning(UNKNOWN_ELEMENT % childNode.tagName)
			return None

	def parseFileNodeState( self, state, xmlNodeState ):
		fileNodeState = FileNodeState(state, xmlNodeState.getAttributeNS(None, "location"))
		self._initNodeState(xmlNodeState, fileNodeState)
		return fileNodeState

	def parseDirectoryNodeState( self, state, xmlNodeState ):
		dirNodeState = DirectoryNodeState( state, xmlNodeState.getAttributeNS(None, "location"))
		self._initNodeState(xmlNodeState, dirNodeState)
		content = self._getNodeState( xmlNodeState, "Content" )
		for child_xml in content.childNodes:
			node = self.parseChildNodeState(state, child_xml)
			if node: dirNodeState._children.append(node)
		return dirNodeState

	def _getNodeState( self, node, nodeName ):
		for child_node in node.childNodes:
			if child_node.nodeName == nodeName:
				return child_node
		return None

	def _getNodeStateText( self, node ):
		result = u""
		for child_node in node.childNodes:
			if child_node.nodeType == child_node.TEXT_NODE:
				result += child_node.data
		return result

	def _initNodeState( self, xmlNodeState, fileSystemNodeState ):
		# We get every attributes information
		attributes_node = self._getNodeState( xmlNodeState, "Attributes" )
		for child_node in attributes_node.childNodes:
			attributes_name  = child_node.nodeName[0].upper()+child_node.nodeName[1:].lower()
			if attributes_name in FILE_SYSTEM_ATTRIBUTES:
				fileSystemNodeState._attributes[attributes_name] = self._getNodeStateText(child_node).strip()
		# We get the signature
		sig = self._getNodeState( xmlNodeState, "signature" )
		fileSystemNodeState._contentSignature = self._getNodeStateText(sig)
		return fileSystemNodeState

	def warning( self, message ):
		"""Outputs a warning message."""
		sys.stderr.write( "WARNING:\t%s\n" % ( message ))
		return None

	def error( self, message ):
		"""Outputs an error message."""
		sys.stderr.write( "ERROR:\t%s\n" % ( message ))
		return None

class StateSerializer:

	def serializeState( self, state ):
		"""Returns an XML document representing the given state."""
		impl = xml.dom.getDOMImplementation()
		# We create the document and the document element
		document = impl.createDocument(None, "State", None)
		document.documentElement.setAttributeNS(None, "location", state.location())
		# Serialize the root node attributes
		document.documentElement.appendChild(
			self.serializeNodeState(document, state.root())
		)
		return document

	def serializeNodeState( self, document, node ):
		"""Returns an XML node representing the given file system node."""
		if isinstance(node, DirectoryNodeState):
			return self.serializeDirectoryNodeState(document, node)
		elif isinstance(node, FileNodeState):
			return self.serializeFileNodeState(document, node)
		else:
			# FIXME: Should never go there
			assert 1==0
			return None

	def serializeFileNodeState( self, document, fileNodeState ):
		"""Returns an XML node representing the given file node."""
		xml_node = document.createElementNS(None, "File")
		return self._serializeNodeState( document, xml_node, fileNodeState )

	def serializeDirectoryNodeState( self, document, dirNodeState=None ):
		"""Returns an XML node representing the given directory node."""
		xml_node = document.createElementNS(None, "Directory")
		content_node = document.createElementNS(None, "Content")
		node = self._serializeNodeState( document, xml_node, dirNodeState )
		for childNode in dirNodeState.getChildren():
			content_node.appendChild(self.serializeNodeState(document, childNode))
		node.appendChild(content_node)
		return node

	def _serializeNodeState( self, document, xmlNodeState, fileNodeState ):
		"""Returns an XML node representing the given file system node,
		properly initilized."""
		# We add the node name and location
		xmlNodeState.setAttributeNS(None, "name", os.path.basename(fileNodeState.location()))
		xmlNodeState.setAttributeNS(None, "location", fileNodeState.location())
		# We create the signature node
		sig = document.createElementNS(None, "signature")
		sig.appendChild(document.createTextNode(fileNodeState.getContentSignature()))
		xmlNodeState.appendChild(sig)
		# We create the "Attributes" node
		attributes_node = document.createElementNS(None, "Attributes")
		for attributes in FILE_SYSTEM_ATTRIBUTES:
			attributes_info = document.createElementNS(None, attributes.lower())
			attributes_info.appendChild(document.createTextNode(
				fileNodeState.getAttribute(attributes)))
			attributes_node.appendChild(attributes_info)
		xmlNodeState.appendChild(attributes_node)
		return xmlNodeState

# EOF-Unix/ASCII------------------------------------@RisingSun//Python//1.0//EN
