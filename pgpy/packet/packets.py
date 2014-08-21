""" packet.py
"""
import abc
import binascii
import calendar
import hashlib
import re

from datetime import datetime

from .fields import DSAPriv
from .fields import DSAPub
from .fields import DSASignature
from .fields import ElGCipherText
from .fields import ElGPriv
from .fields import ElGPub
from .fields import RSACipherText
from .fields import RSAPriv
from .fields import RSAPub
from .fields import RSASignature
from .fields import SubPackets
from .fields import UserAttributeSubPackets

from .types import Packet
from .types import Primary
from .types import Private
from .types import Public
from .types import Sub
from .types import VersionedPacket

from ..constants import CompressionAlgorithm
from ..constants import HashAlgorithm
from ..constants import PubKeyAlgorithm
from ..constants import SignatureType
from ..constants import TrustFlags
from ..constants import TrustLevel

from ..decorators import TypedProperty

from ..types import Fingerprint


class PKESessionKey(VersionedPacket):
    __typeid__ = 0x01
    __ver__ = 0


class PKESessionKeyV3(PKESessionKey):
    """
    5.1.  Public-Key Encrypted Session Key Packets (Tag 1)

    A Public-Key Encrypted Session Key packet holds the session key used
    to encrypt a message.  Zero or more Public-Key Encrypted Session Key
    packets and/or Symmetric-Key Encrypted Session Key packets may
    precede a Symmetrically Encrypted Data Packet, which holds an
    encrypted message.  The message is encrypted with the session key,
    and the session key is itself encrypted and stored in the Encrypted
    Session Key packet(s).  The Symmetrically Encrypted Data Packet is
    preceded by one Public-Key Encrypted Session Key packet for each
    OpenPGP key to which the message is encrypted.  The recipient of the
    message finds a session key that is encrypted to their public key,
    decrypts the session key, and then uses the session key to decrypt
    the message.

    The body of this packet consists of:

     - A one-octet number giving the version number of the packet type.
       The currently defined value for packet version is 3.

     - An eight-octet number that gives the Key ID of the public key to
       which the session key is encrypted.  If the session key is
       encrypted to a subkey, then the Key ID of this subkey is used
       here instead of the Key ID of the primary key.

     - A one-octet number giving the public-key algorithm used.

     - A string of octets that is the encrypted session key.  This
       string takes up the remainder of the packet, and its contents are
       dependent on the public-key algorithm used.

    Algorithm Specific Fields for RSA encryption

     - multiprecision integer (MPI) of RSA encrypted value m**e mod n.

    Algorithm Specific Fields for Elgamal encryption:

     - MPI of Elgamal (Diffie-Hellman) value g**k mod p.

     - MPI of Elgamal (Diffie-Hellman) value m * y**k mod p.

    The value "m" in the above formulas is derived from the session key
    as follows.  First, the session key is prefixed with a one-octet
    algorithm identifier that specifies the symmetric encryption
    algorithm used to encrypt the following Symmetrically Encrypted Data
    Packet.  Then a two-octet checksum is appended, which is equal to the
    sum of the preceding session key octets, not including the algorithm
    identifier, modulo 65536.  This value is then encoded as described in
    PKCS#1 block encoding EME-PKCS1-v1_5 in Section 7.2.1 of [RFC3447] to
    form the "m" value used in the formulas above.  See Section 13.1 of
    this document for notes on OpenPGP's use of PKCS#1.

    Note that when an implementation forms several PKESKs with one
    session key, forming a message that can be decrypted by several keys,
    the implementation MUST make a new PKCS#1 encoding for each key.

    An implementation MAY accept or use a Key ID of zero as a "wild card"
    or "speculative" Key ID.  In this case, the receiving implementation
    would try all available private keys, checking for a valid decrypted
    session key.  This format helps reduce traffic analysis of messages.
    """
    __ver__ = 3

    @TypedProperty
    def encrypter(self):
        return self._encrypter

    @encrypter.bytearray
    def encrypter(self, val):
        self._encrypter = binascii.hexlify(val).upper().decode('latin-1')

    @TypedProperty
    def pkalg(self):
        return self._pkalg

    @pkalg.PubKeyAlgorithm
    def pkalg(self, val):
        self._pkalg = val

        _c = {PubKeyAlgorithm.RSAEncryptOrSign: RSACipherText,
              PubKeyAlgorithm.RSAEncrypt: RSACipherText,
              PubKeyAlgorithm.ElGamal: ElGCipherText,
              PubKeyAlgorithm.FormerlyElGamalEncryptOrSign: ElGCipherText}

        if val in _c:
            self.ct = _c[val]()

        else:
            self.ct = None

    @pkalg.int
    def pkalg(self, val):
        self.pkalg = PubKeyAlgorithm(val)

    def __init__(self):
        super(PKESessionKeyV3, self).__init__()
        self.encrypter = bytearray(8)
        self.pkalg = 0
        self.ct = None

    def __bytes__(self):
        _bytes = bytearray()
        _bytes += super(PKESessionKeyV3, self).__bytes__()
        _bytes += binascii.unhexlify(self.encrypter.encode())
        _bytes.append(self.pkalg)
        _bytes += self.ct.__bytes__() if self.ct is not None else b'\x00' * (self.header.length - 10)
        return bytes(_bytes)

    def parse(self, packet):
        super(PKESessionKeyV3, self).parse(packet)
        self.encrypter = packet[:8]
        del packet[:8]

        self.pkalg = packet[0]
        del packet[0]

        if self.ct is not None:
            self.ct.parse(packet)

        else:
            del packet[:(self.header.length - 18)]


class Signature(VersionedPacket):
    __typeid__ = 0x02
    __ver__ = 0


class SignatureV4(Signature):
    """
    5.2.3.  Version 4 Signature Packet Format

    The body of a version 4 Signature packet contains:

     - One-octet version number (4).

     - One-octet signature type.

     - One-octet public-key algorithm.

     - One-octet hash algorithm.

     - Two-octet scalar octet count for following hashed subpacket data.
       Note that this is the length in octets of all of the hashed
       subpackets; a pointer incremented by this number will skip over
       the hashed subpackets.

     - Hashed subpacket data set (zero or more subpackets).

     - Two-octet scalar octet count for the following unhashed subpacket
       data.  Note that this is the length in octets of all of the
       unhashed subpackets; a pointer incremented by this number will
       skip over the unhashed subpackets.

     - Unhashed subpacket data set (zero or more subpackets).

     - Two-octet field holding the left 16 bits of the signed hash
       value.

     - One or more multiprecision integers comprising the signature.
       This portion is algorithm specific, as described above.

    The concatenation of the data being signed and the signature data
    from the version number through the hashed subpacket data (inclusive)
    is hashed.  The resulting hash value is what is signed.  The left 16
    bits of the hash are included in the Signature packet to provide a
    quick test to reject some invalid signatures.

    There are two fields consisting of Signature subpackets.  The first
    field is hashed with the rest of the signature data, while the second
    is unhashed.  The second set of subpackets is not cryptographically
    protected by the signature and should include only advisory
    information.

    The algorithms for converting the hash function result to a signature
    are described in a section below.
    """
    __typeid__ = 0x02
    __ver__ = 4

    @TypedProperty
    def sigtype(self):
        return self._sigtype

    @sigtype.SignatureType
    def sigtype(self, val):
        self._sigtype = val

    @sigtype.int
    def sigtype(self, val):
        self.sigtype = SignatureType(val)

    @TypedProperty
    def pubalg(self):
        return self._pubalg

    @pubalg.PubKeyAlgorithm
    def pubalg(self, val):
        self._pubalg = val
        if val in [PubKeyAlgorithm.RSAEncryptOrSign, PubKeyAlgorithm.RSAEncrypt, PubKeyAlgorithm.RSASign]:
            self.signature = RSASignature()

        elif val == PubKeyAlgorithm.DSA:
            self.signature = DSASignature()

    @pubalg.int
    def pubalg(self, val):
        self.pubalg = PubKeyAlgorithm(val)

    @TypedProperty
    def halg(self):
        return self._halg

    @halg.HashAlgorithm
    def halg(self, val):
        self._halg = val

    @halg.int
    def halg(self, val):
        try:
            self.halg = HashAlgorithm(val)

        except ValueError:
            self._halg = val

    @property
    def signature(self):
        return self._signature

    @signature.setter
    def signature(self, val):
        self._signature = val

    def __init__(self):
        super(Signature, self).__init__()
        self._sigtype = None
        self._pubalg = None
        self._halg = None
        self.subpackets = SubPackets()
        self.hash2 = bytearray(2)
        self.signature = None

    def __bytes__(self):
        _bytes = bytearray()
        _bytes += super(Signature, self).__bytes__()
        _bytes += self.int_to_bytes(self.sigtype)
        _bytes += self.int_to_bytes(self.pubalg)
        _bytes += self.int_to_bytes(self.halg)
        _bytes += self.subpackets.__bytes__()
        _bytes += self.hash2
        _bytes += self.signature.__bytes__()

        return bytes(_bytes)

    def parse(self, packet):
        super(Signature, self).parse(packet)
        self.sigtype = packet[0]
        del packet[0]

        self.pubalg = packet[0]
        del packet[0]

        self.halg = packet[0]
        del packet[0]

        self.subpackets.parse(packet)

        self.hash2 = packet[:2]
        del packet[:2]

        self.signature.parse(packet)


class SKESessionKey(VersionedPacket):
    __typeid__ = 0x03
    __ver__ = 0


class SKESessionKeyV4(SKESessionKey):
    # __ver__ = 4
    pass


class OnePassSignature(VersionedPacket):
    __typeid__ = 0x04
    __ver__ = 0


class OnePassSignatureV4(OnePassSignature):
    __ver__ = 4


class PrivKey(VersionedPacket, Primary, Private):
    __typeid__ = 0x05
    __ver__ = 0


class PubKey(VersionedPacket, Primary, Public):
    __typeid__ = 0x06
    __ver__ = 0

    @abc.abstractproperty
    def fingerprint(self):
        return ""


class PubKeyV4(PubKey):
    __ver__ = 4

    @TypedProperty
    def created(self):
        return self._created

    @created.datetime
    def created(self, val):
        self._created = val

    @created.int
    def created(self, val):
        self.created = datetime.utcfromtimestamp(val)

    @created.bytearray
    @created.bytes
    def created(self, val):
        self.created = self.bytes_to_int(val)

    @TypedProperty
    def pkalg(self):
        return self._pkalg

    @pkalg.PubKeyAlgorithm
    def pkalg(self, val):
        self._pkalg = val

        _c = {
            # True means public
            (True, PubKeyAlgorithm.RSAEncryptOrSign): RSAPub,
            (True, PubKeyAlgorithm.RSAEncrypt): RSAPub,
            (True, PubKeyAlgorithm.RSASign): RSAPub,
            (True, PubKeyAlgorithm.DSA): DSAPub,
            (True, PubKeyAlgorithm.ElGamal): ElGPub,
            (True, PubKeyAlgorithm.FormerlyElGamalEncryptOrSign): ElGPub,
            # False means private
            (False, PubKeyAlgorithm.RSAEncryptOrSign): RSAPriv,
            (False, PubKeyAlgorithm.RSAEncrypt): RSAPriv,
            (False, PubKeyAlgorithm.RSASign): RSAPriv,
            (False, PubKeyAlgorithm.DSA): DSAPriv,
            (False, PubKeyAlgorithm.ElGamal): ElGPriv,
            (False, PubKeyAlgorithm.FormerlyElGamalEncryptOrSign): ElGPriv,
        }

        k = (self.public, self.pkalg)

        if k in _c:
            self.keymaterial = _c[k]()

        else:
            self.keymaterial = None

    @pkalg.int
    def pkalg(self, val):
        self.pkalg = PubKeyAlgorithm(val)

    @property
    def public(self):
        return isinstance(self, PubKey) and not isinstance(self, PrivKey)

    @property
    def fingerprint(self):
        # A V4 fingerprint is the 160-bit SHA-1 hash of the octet 0x99, followed by the two-octet packet length,
        # followed by the entire Public-Key packet starting with the version field.  The Key ID is the
        # low-order 64 bits of the fingerprint.
        fp = hashlib.new('sha1')

        plen = self.keymaterial.publen()
        bcde_len = self.int_to_bytes(6 + plen, 2)

        # a.1) 0x99 (1 octet)
        # a.2) high-order length octet
        # a.3) low-order length octet
        fp.update(b'\x99' + bcde_len[:1] + bcde_len[-1:])
        # b) version number = 4 (1 octet);
        fp.update(b'\x04')
        # c) timestamp of key creation (4 octets);
        fp.update(self.int_to_bytes(calendar.timegm(self.created.timetuple()), 4))
        # d) algorithm (1 octet): 17 = DSA (example);
        fp.update(self.int_to_bytes(self.pkalg))
        # e) Algorithm-specific fields.
        fp.update(self.keymaterial.__bytes__()[:plen])

        # and return the digest
        return Fingerprint(fp.hexdigest().upper())

    def __init__(self):
        super(PubKeyV4, self).__init__()
        self.created = datetime.utcnow()
        self.pkalg = 0

    def __bytes__(self):
        _bytes = bytearray()
        _bytes += super(PubKeyV4, self).__bytes__()
        _bytes += self.int_to_bytes(calendar.timegm(self.created.timetuple()), 4)
        _bytes += self.int_to_bytes(self.pkalg)
        _bytes += self.keymaterial.__bytes__()
        return bytes(_bytes)

    def parse(self, packet):
        super(PubKeyV4, self).parse(packet)

        self.created = packet[:4]
        del packet[:4]

        self.pkalg = packet[0]
        del packet[0]

        # bound keymaterial to the remaining length of the packet
        pend = self.header.length - 6
        self.keymaterial.parse(packet[:pend])
        del packet[:pend]


class PrivKeyV4(PrivKey, PubKeyV4):
    __ver__ = 4

    @property
    def protected(self):
        return bool(self.keymaterial)

    def unprotect(self, passphrase):
        self.keymaterial.decrypt_keyblob(passphrase)
        del passphrase


class PrivSubKey(VersionedPacket, Sub, Private):
    __typeid__ = 0x07
    __ver__ = 0


class PrivSubKeyV4(PrivSubKey, PrivKeyV4):
    __ver__ = 4


class CompressedData(Packet):
    """
    5.6.  Compressed Data Packet (Tag 8)

    The Compressed Data packet contains compressed data.  Typically, this
    packet is found as the contents of an encrypted packet, or following
    a Signature or One-Pass Signature packet, and contains a literal data
    packet.

    The body of this packet consists of:

     - One octet that gives the algorithm used to compress the packet.

     - Compressed data, which makes up the remainder of the packet.

    A Compressed Data Packet's body contains an block that compresses
    some set of packets.  See section "Packet Composition" for details on
    how messages are formed.

    ZIP-compressed packets are compressed with raw RFC 1951 [RFC1951]
    DEFLATE blocks.  Note that PGP V2.6 uses 13 bits of compression.  If
    an implementation uses more bits of compression, PGP V2.6 cannot
    decompress it.

    ZLIB-compressed packets are compressed with RFC 1950 [RFC1950] ZLIB-
    style blocks.

    BZip2-compressed packets are compressed using the BZip2 [BZ2]
    algorithm.
    """
    __typeid__ = 0x08

    @TypedProperty
    def calg(self):
        return self._calg

    @calg.CompressionAlgorithm
    def calg(self, val):
        self._calg = val

    @calg.int
    def calg(self, val):
        self.calg = CompressionAlgorithm(val)

    def __init__(self):
        super(CompressedData, self).__init__()
        self._calg = None
        self.cpacket = None

    def __bytes__(self):
        _bytes = bytearray()
        _bytes += super(CompressedData, self).__bytes__()
        _bytes.append(self.calg)
        _bytes += self.calg.compress(self.cpacket.__bytes__())
        return bytes(_bytes)

    def parse(self, packet):
        super(CompressedData, self).parse(packet)
        self.calg = packet[0]
        del packet[0]

        cdata = packet[:self.header.length - 1]
        del packet[:self.header.length - 1]
        self.cpacket = Packet(bytearray(self.calg.decompress(cdata)))


class SKEData(Packet):
    # __typeid__ = 0x09
    pass


class Marker(Packet):
    # __typeid__ = 0x10
    pass


class LiteralData(Packet):
    """
    5.9.  Literal Data Packet (Tag 11)

    A Literal Data packet contains the body of a message; data that is
    not to be further interpreted.

    The body of this packet consists of:

     - A one-octet field that describes how the data is formatted.

    If it is a 'b' (0x62), then the Literal packet contains binary data.
    If it is a 't' (0x74), then it contains text data, and thus may need
    line ends converted to local form, or other text-mode changes.  The
    tag 'u' (0x75) means the same as 't', but also indicates that
    implementation believes that the literal data contains UTF-8 text.

    Early versions of PGP also defined a value of 'l' as a 'local' mode
    for machine-local conversions.  RFC 1991 [RFC1991] incorrectly stated
    this local mode flag as '1' (ASCII numeral one).  Both of these local
    modes are deprecated.

     - File name as a string (one-octet length, followed by a file
       name).  This may be a zero-length string.  Commonly, if the
       source of the encrypted data is a file, this will be the name of
       the encrypted file.  An implementation MAY consider the file name
       in the Literal packet to be a more authoritative name than the
       actual file name.

    If the special name "_CONSOLE" is used, the message is considered to
    be "for your eyes only".  This advises that the message data is
    unusually sensitive, and the receiving program should process it more
    carefully, perhaps avoiding storing the received data to disk, for
    example.

     - A four-octet number that indicates a date associated with the
       literal data.  Commonly, the date might be the modification date
       of a file, or the time the packet was created, or a zero that
       indicates no specific time.

     - The remainder of the packet is literal data.

       Text data is stored with <CR><LF> text endings (i.e., network-
       normal line endings).  These should be converted to native line
       endings by the receiving software.
    """
    __typeid__ = 0x0B

    @TypedProperty
    def mtime(self):
        return self._mtime

    @mtime.datetime
    def mtime(self, val):
        self._mtime = val

    @mtime.int
    def mtime(self, val):
        self.mtime = datetime.utcfromtimestamp(val)

    @mtime.bytes
    @mtime.bytearray
    def mtime(self, val):
        self.mtime = self.bytes_to_int(val)

    def __init__(self):
        super(LiteralData, self).__init__()
        self.format = 'b'
        self.filename = ''
        self.mtime = datetime.utcnow()
        self.contents = bytearray()

    def __bytes__(self):
        _bytes = bytearray()
        _bytes += super(LiteralData, self).__bytes__()
        _bytes += self.format.encode('latin-1')
        _bytes.append(len(self.filename))
        _bytes += self.filename.encode('latin-1')
        _bytes += self.int_to_bytes(calendar.timegm(self.mtime.timetuple()), 4)
        _bytes += self.contents
        return bytes(_bytes)

    def parse(self, packet):
        super(LiteralData, self).parse(packet)
        self.format = chr(packet[0])
        del packet[0]

        fnl = packet[0]
        del packet[0]

        self.filename = packet[:fnl].decode()
        del packet[:fnl]

        self.mtime = packet[:4]
        del packet[:4]

        self.contents = packet[:self.header.length - (6 + fnl)]
        del packet[:self.header.length - (6 + fnl)]


class Trust(Packet):
    """
    5.10.  Trust Packet (Tag 12)

    The Trust packet is used only within keyrings and is not normally
    exported.  Trust packets contain data that record the user's
    specifications of which key holders are trustworthy introducers,
    along with other information that implementing software uses for
    trust information.  The format of Trust packets is defined by a given
    implementation.

    Trust packets SHOULD NOT be emitted to output streams that are
    transferred to other users, and they SHOULD be ignored on any input
    other than local keyring files.
    """
    __typeid__ = 0x0C

    @TypedProperty
    def trustlevel(self):
        return self._trustlevel

    @trustlevel.TrustLevel
    def trustlevel(self, val):
        self._trustlevel = val

    @trustlevel.int
    def trustlevel(self, val):
        self.trustlevel = TrustLevel(val & 0x0F)

    @TypedProperty
    def trustflags(self):
        return self._trustflags

    @trustflags.list
    def trustflags(self, val):
        self._trustflags = val

    @trustflags.int
    def trustflags(self, val):
        self._trustflags = TrustFlags & val

    def __init__(self):
        super(Trust, self).__init__()
        self.trustlevel = TrustLevel.Unknown
        self.trustflags = []

    def __bytes__(self):
        _bytes = bytearray()
        _bytes += super(Trust, self).__bytes__()
        _bytes += self.int_to_bytes(self.trustlevel + sum(self.trustflags), 2)
        return bytes(_bytes)

    def parse(self, packet):
        super(Trust, self).parse(packet)
        # self.trustlevel = packet[0] & 0x1f
        t = self.bytes_to_int(packet[:2])
        del packet[:2]

        self.trustlevel = t
        self.flags = t


class UserID(Packet):
    """
    5.11.  User ID Packet (Tag 13)

    A User ID packet consists of UTF-8 text that is intended to represent
    the name and email address of the key holder.  By convention, it
    includes an RFC 2822 [RFC2822] mail name-addr, but there are no
    restrictions on its content.  The packet length in the header
    specifies the length of the User ID.
    """
    __typeid__ = 0x0D

    def __init__(self):
        super(UserID, self).__init__()
        self.name = ""
        self.comment = ""
        self.email = ""

    def __bytes__(self):
        _bytes = bytearray()
        _bytes += super(UserID, self).__bytes__()
        _bytes += "{name:s}{comment:s}{email:s}".format(
            name=self.name,
            comment=" ({comment:s})".format(comment=self.comment) if self.comment not in [None, ""] else "",
            email=" <{email:s}>".format(email=self.email) if self.email not in [None, ""] else "").encode()
        return bytes(_bytes)

    def parse(self, packet):
        super(UserID, self).parse(packet)

        uid_text = packet[:self.header.length].decode('latin-1')
        del packet[:self.header.length]

        # came across a UID packet with no payload. If that happens, don't bother trying to parse anything!
        if self.header.length > 0:
            uid = re.match(r"""^
                               # name should always match something
                               (?P<name>.+?)
                               # comment *optionally* matches text in parens following name
                               # this should never come after email and must be followed immediately by
                               # either the email field, or the end of the packet.
                               (\ \((?P<comment>.+?)\)(?=(\ <|$)))?
                               # email *optionally* matches text in angle brackets following name or comment
                               # this should never come before a comment, if comment exists,
                               # but can immediately follow name if comment does not exist
                               (\ <(?P<email>.+)>)?
                               $
                            """, uid_text, flags=re.VERBOSE).groupdict()

            self.name = uid['name']
            self.comment = uid['comment']
            self.email = uid['email']


class PubSubKey(VersionedPacket, Sub, Public):
    __typeid__ = 0x0E
    __ver__ = 0


class PubSubKeyV4(PubSubKey, PubKeyV4):
    __ver__ = 4


class UserAttribute(Packet):
    """
    5.12.  User Attribute Packet (Tag 17)

    The User Attribute packet is a variation of the User ID packet.  It
    is capable of storing more types of data than the User ID packet,
    which is limited to text.  Like the User ID packet, a User Attribute
    packet may be certified by the key owner ("self-signed") or any other
    key owner who cares to certify it.  Except as noted, a User Attribute
    packet may be used anywhere that a User ID packet may be used.

    While User Attribute packets are not a required part of the OpenPGP
    standard, implementations SHOULD provide at least enough
    compatibility to properly handle a certification signature on the
    User Attribute packet.  A simple way to do this is by treating the
    User Attribute packet as a User ID packet with opaque contents, but
    an implementation may use any method desired.

    The User Attribute packet is made up of one or more attribute
    subpackets.  Each subpacket consists of a subpacket header and a
    body.  The header consists of:

     - the subpacket length (1, 2, or 5 octets)

     - the subpacket type (1 octet)

    and is followed by the subpacket specific data.

    The only currently defined subpacket type is 1, signifying an image.
    An implementation SHOULD ignore any subpacket of a type that it does
    not recognize.  Subpacket types 100 through 110 are reserved for
    private or experimental use.
    """
    __typeid__ = 0x11

    def __init__(self):
        super(UserAttribute, self).__init__()
        self.subpackets = UserAttributeSubPackets()

    def __bytes__(self):
        _bytes = bytearray()
        _bytes += super(UserAttribute, self).__bytes__()
        _bytes += self.subpackets.__bytes__()
        return bytes(_bytes)

    def parse(self, packet):
        super(UserAttribute, self).parse(packet)

        plen = len(packet)
        while self.header.length > (plen - len(packet)):
            self.subpackets.parse(packet)


class IntegrityProtectedSKEData(VersionedPacket):
    __typeid__ = 0x12
    __ver__ = 0


class IntegrityProtectedSKEDataV1(IntegrityProtectedSKEData):
    # __ver__ = 1
    pass


class MDC(Packet):
    # __typeid__ = 0x13
    pass
