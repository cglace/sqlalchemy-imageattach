from __future__ import absolute_import, with_statement

import hashlib
import os.path

from pytest import fixture, raises
from sqlalchemy.orm import relationship
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.schema import Column, ForeignKey
from sqlalchemy.types import Integer, String
from wand.image import Image as WandImage

from sqlalchemy_imageattach.context import store_context
from sqlalchemy_imageattach.entity import Image, image_attachment
from sqlalchemy_imageattach.stores.fs import FileSystemStore
from .conftest import Base, sample_images_dir


class ExpectedException(Exception):
    """Exception to be expected to rise."""


@fixture
def tmp_store(request, tmpdir):
    request.addfinalizer(tmpdir.remove)
    return FileSystemStore(tmpdir.strpath, 'http://localhost/')


class Something(Base):

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    cover = image_attachment('SomethingCover')

    __tablename__ = 'something'


class SomethingCover(Base, Image):

    something_id = Column(Integer, ForeignKey(Something.id), primary_key=True)
    something = relationship(Something)

    __tablename__ = 'something_cover'

    @property
    def object_id(self):
        return self.something_id


def from_raw_file(fx_session, tmp_store):
    something = Something(name='some name')
    with open(os.path.join(sample_images_dir, 'iu.jpg')) as f:
        expected = f.read()
        f.seek(0)
        img = something.cover.from_raw_file(f, tmp_store, original=True)
        assert something.cover.original is img
        with fx_session.begin():
            fx_session.add(something)
            assert something.cover.original is img
    assert something.cover.count() == 1
    assert img is something.cover.original
    with something.cover.open_file(tmp_store) as f:
        actual = f.read()
    assert actual == expected
    # overwriting
    something.cover.generate_thumbnail(ratio=0.5, store=tmp_store)
    assert something.cover.count() == 2
    with open(os.path.join(sample_images_dir, 'iu2.jpg')) as f:
        expected = f.read()
        f.seek(0)
        img2 = something.cover.from_raw_file(f, tmp_store, original=True)
        assert something.cover.original is img2
        with fx_session.begin():
            fx_session.add(something)
            assert something.cover.original is img2
    assert something.cover.count() == 1
    assert img2 is something.cover.original
    with something.cover.open_file(tmp_store) as f:
        actual = f.read()
    assert actual == expected
    # overwriting + thumbnail generation
    something.cover.generate_thumbnail(ratio=0.5, store=tmp_store)
    assert something.cover.count() == 2
    with open(os.path.join(sample_images_dir, 'iu.jpg')) as f:
        expected = f.read()
        f.seek(0)
        img3 = something.cover.from_raw_file(f, tmp_store, original=True)
        something.cover.generate_thumbnail(width=10, store=tmp_store)
        something.cover.generate_thumbnail(width=20, store=tmp_store)
        assert something.cover.original is img3
        with fx_session.begin():
            fx_session.add(something)
            assert something.cover.original is img3
    assert something.cover.count() == 3
    assert frozenset(img.width for img in something.cover) == frozenset([
        10, 20, img3.width
    ])
    assert img3 is something.cover.original
    with something.cover.open_file(tmp_store) as f:
        actual = f.read()
    assert actual == expected
    with something.cover.find_thumbnail(width=10).open_file(tmp_store) as f:
        with WandImage(file=f) as wand:
            assert wand.width == 10
    with something.cover.find_thumbnail(width=20).open_file(tmp_store) as f:
        with WandImage(file=f) as wand:
            assert wand.width == 20


def test_from_raw_file_implicitly(fx_session, tmp_store):
    with store_context(tmp_store):
        something = Something(name='some name')
        with open(os.path.join(sample_images_dir, 'iu.jpg')) as f:
            expected = f.read()
            f.seek(0)
            img = something.cover.from_raw_file(f, original=True)
            assert something.cover.original is img
            with fx_session.begin():
                fx_session.add(something)
                assert something.cover.original is img
    assert something.cover.count() == 1
    assert img is something.cover.original
    with store_context(tmp_store):
        with something.cover.open_file() as f:
            actual = f.read()
    assert actual == expected


def test_from_blob(fx_session, tmp_store):
    something = Something(name='some name')
    with open(os.path.join(sample_images_dir, 'iu.jpg')) as f:
        expected = f.read()
        img = something.cover.from_blob(expected, tmp_store)
        assert something.cover.original is img
        with fx_session.begin():
            fx_session.add(something)
            assert something.cover.original is img
    assert something.cover.count() == 1
    assert img is something.cover.original
    assert something.cover.make_blob(tmp_store) == expected
    # overwriting
    something.cover.generate_thumbnail(ratio=0.5, store=tmp_store)
    assert something.cover.count() == 2
    with open(os.path.join(sample_images_dir, 'iu2.jpg')) as f:
        expected = f.read()
        img2 = something.cover.from_blob(expected, tmp_store)
        assert something.cover.original is img2
        with fx_session.begin():
            fx_session.add(something)
            assert something.cover.original is img2
    assert something.cover.count() == 1
    assert img2 is something.cover.original
    assert something.cover.make_blob(tmp_store) == expected


def test_from_blob_implicitly(fx_session, tmp_store):
    with store_context(tmp_store):
        something = Something(name='some name')
        with open(os.path.join(sample_images_dir, 'iu.jpg')) as f:
            expected = f.read()
            img = something.cover.from_blob(expected)
            assert something.cover.original is img
            with fx_session.begin():
                fx_session.add(something)
                assert something.cover.original is img
    assert something.cover.count() == 1
    assert img is something.cover.original
    with store_context(tmp_store):
        assert something.cover.make_blob() == expected


def test_rollback_from_raw_file(fx_session, tmp_store):
    """When the transaction fails, file shoud not be stored."""
    something = Something(name='some name')
    with fx_session.begin():
        fx_session.add(something)
    with open(os.path.join(sample_images_dir, 'iu.jpg')) as f:
        with raises(ExpectedException):
            with fx_session.begin():
                image = something.cover.from_raw_file(f, tmp_store,
                                                      original=True)
                assert something.cover.original is image
                fx_session.flush()
                assert something.cover.original is image
                args = (image.object_type, image.object_id, image.width,
                        image.height, image.mimetype)
                raise ExpectedException()
    assert something.cover.count() == 0
    assert something.cover.original is None
    with raises(IOError):
        print tmp_store.get_file(*args)


def test_rollback_from_raw_file_implitcitly(fx_session, tmp_store):
    """When the transaction fails, file shoud not be stored."""
    with store_context(tmp_store):
        something = Something(name='some name')
        with fx_session.begin():
            fx_session.add(something)
        with open(os.path.join(sample_images_dir, 'iu.jpg')) as f:
            with raises(ExpectedException):
                with fx_session.begin():
                    image = something.cover.from_raw_file(f, original=True)
                    assert something.cover.original is image
                    fx_session.flush()
                    assert something.cover.original is image
                    args = (image.object_type, image.object_id, image.width,
                            image.height, image.mimetype)
                    raise ExpectedException()
    assert something.cover.count() == 0
    assert something.cover.original is None
    with raises(IOError):
        print tmp_store.get_file(*args)


def test_delete(fx_session, tmp_store):
    with store_context(tmp_store):
        something = Something(name='some name')
        with open(os.path.join(sample_images_dir, 'iu.jpg')) as f:
            image = something.cover.from_file(f)
            assert something.cover.original is image
            with fx_session.begin():
                fx_session.add(something)
                assert something.cover.original is image
            args = (image.object_type, image.object_id, image.width,
                    image.height, image.mimetype)
        with fx_session.begin():
            fx_session.delete(image)
        assert something.cover.original is None
        with raises(IOError):
            tmp_store.get_file(*args)


def test_rollback_from_delete(fx_session, tmp_store):
    """When the transaction fails, file should not be deleted."""
    with store_context(tmp_store):
        something = Something(name='some name')
        with open(os.path.join(sample_images_dir, 'iu.jpg')) as f:
            expected = f.read()
        image = something.cover.from_blob(expected)
        assert something.cover.original is image
        with fx_session.begin():
            fx_session.add(something)
            assert something.cover.original is image
        with raises(ExpectedException):
            with fx_session.begin():
                assert something.cover.original is image
                fx_session.delete(image)
                raise ExpectedException()
        with tmp_store.open(image) as f:
            actual = f.read()
    assert something.cover.original is image
    assert actual == expected


def test_delete_parent(fx_session, tmp_store):
    with store_context(tmp_store):
        something = Something(name='some name')
        with open(os.path.join(sample_images_dir, 'iu.jpg')) as f:
            image = something.cover.from_file(f)
            assert something.cover.original is image
            with fx_session.begin():
                fx_session.add(something)
            assert something.cover.original is image
            args = (image.object_type, image.object_id, image.width,
                    image.height, image.mimetype)
        with fx_session.begin():
            assert something.cover.original is image
            fx_session.delete(something)
        assert something.cover.original is None
        with raises(IOError):
            tmp_store.get_file(*args)


class Samething(Base):
    """Not S'o'mething, but s'a'mething."""

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    cover = image_attachment('SamethingCover')

    __tablename__ = 'samething'


class SamethingCover(Base, Image):

    samething_id = Column(Integer, ForeignKey(Samething.id), primary_key=True)
    samething = relationship(Samething)

    __tablename__ = 'samething_cover'

    @property
    def object_id(self):
        return self.samething_id


def test_delete_from_persistence(fx_session, tmp_store):
    with store_context(tmp_store):
        something = Something(name='some name')
        with open(os.path.join(sample_images_dir, 'iu.jpg')) as f:
            image = something.cover.from_file(f)
            assert something.cover.original is image
            with fx_session.begin():
                fx_session.add(something)
            assert something.cover.original is image
            args = ('samething-cover', image.object_id, image.width,
                    image.height, image.mimetype)
            fx_session.execute('INSERT INTO samething '
                               'SELECT * FROM something')
            fx_session.execute('INSERT INTO samething_cover '
                               'SELECT * FROM something_cover')
            f.seek(0)
            tmp_store.put_file(f, *(args + (False,)))
        cover = fx_session.query(SamethingCover) \
                          .filter_by(samething_id=something.id) \
                          .one()
        with fx_session.begin():
            fx_session.delete(cover)
        samething = fx_session.query(Samething).filter_by(id=something.id).one()
        assert samething.cover.original is None
        with raises(IOError):
            print tmp_store.get_file(*args)


def test_delete_parent_from_persistence(fx_session, tmp_store):
    with store_context(tmp_store):
        something = Something(name='some name')
        with open(os.path.join(sample_images_dir, 'iu.jpg')) as f:
            image = something.cover.from_file(f)
            assert something.cover.original is image
            with fx_session.begin():
                fx_session.add(something)
            assert something.cover.original is image
            args = ('samething-cover', image.object_id, image.width,
                    image.height, image.mimetype)
            fx_session.execute('INSERT INTO samething '
                               'SELECT * FROM something')
            fx_session.execute('INSERT INTO samething_cover '
                               'SELECT * FROM something_cover')
            f.seek(0)
            tmp_store.put_file(f, *(args + (False,)))
        samething = fx_session.query(Samething).filter_by(id=something.id).one()
        with fx_session.begin():
            fx_session.delete(samething)
        assert samething.cover.original is None
        with raises(IOError):
            print tmp_store.get_file(*args)


def test_rollback_from_delete_parent(fx_session, tmp_store):
    """When the transaction fails, file should not be deleted."""
    with store_context(tmp_store):
        something = Something(name='some name')
        with open(os.path.join(sample_images_dir, 'iu.jpg')) as f:
            expected = f.read()
        image = something.cover.from_blob(expected)
        assert something.cover.original is image
        with fx_session.begin():
            fx_session.add(something)
            assert something.cover.original is image
        with raises(ExpectedException):
            with fx_session.begin():
                assert something.cover.original is image
                fx_session.delete(something)
                raise ExpectedException()
        with tmp_store.open(image) as f:
            actual = f.read()
    assert actual == expected
    assert something.cover.original is image


def test_generate_thumbnail(fx_session, tmp_store):
    something = Something(name='some name')
    with raises(IOError):
        something.cover.generate_thumbnail(ratio=0.5, store=tmp_store)
    with open(os.path.join(sample_images_dir, 'iu.jpg')) as f:
        original = something.cover.from_file(f, tmp_store)
        assert something.cover.original is original
        double = something.cover.generate_thumbnail(ratio=2, store=tmp_store)
        thumbnail = something.cover.generate_thumbnail(height=320,
                                                       store=tmp_store)
        assert (something.cover.generate_thumbnail(width=810, store=tmp_store)
                is double)
        with fx_session.begin():
            fx_session.add(something)
            assert something.cover.original is original
    assert something.cover.count() == 3
    assert original is something.cover.original
    assert double.size == (810, 1280)
    assert thumbnail.size == (202, 320)
    assert (something.cover.generate_thumbnail(width=202, store=tmp_store)
            is thumbnail)
    with fx_session.begin():
        x3 = something.cover.generate_thumbnail(width=1215, store=tmp_store)
    assert something.cover.count() == 4
    x3.size == (1215, 1920)
    for size in [(405, 640), (810, 1280), (202, 320)]:
        fail_hint = 'size = {0!r}, sizes = {1!r}'.format(
            size, [i.size for i in something.cover]
        )
        assert something.cover.find_thumbnail(width=size[0]).size == size, \
               fail_hint
        assert something.cover.find_thumbnail(height=size[1]).size == size, \
               fail_hint
        assert something.cover.find_thumbnail(*size).size == size, fail_hint
    with raises(NoResultFound):
        something.cover.find_thumbnail(270)
    with raises(NoResultFound):
        something.cover.find_thumbnail(height=426)
    with raises(NoResultFound):
        something.cover.find_thumbnail(270, 426)


def test_generate_thumbnail_implicitly(fx_session, tmp_store):
    with store_context(tmp_store):
        something = Something(name='some name')
        with raises(IOError):
            something.cover.generate_thumbnail(ratio=0.5)
        with open(os.path.join(sample_images_dir, 'iu.jpg')) as f:
            original = something.cover.from_file(f)
            assert something.cover.original is original
            double = something.cover.generate_thumbnail(ratio=2)
            thumbnail = something.cover.generate_thumbnail(height=320)
            assert something.cover.generate_thumbnail(width=810) is double
            with fx_session.begin():
                fx_session.add(something)
                assert something.cover.original is original
        assert something.cover.count() == 3
        assert original is something.cover.original
        assert double.size == (810, 1280)
        assert thumbnail.size == (202, 320)
        assert something.cover.generate_thumbnail(width=202) is thumbnail
        with fx_session.begin():
            x3 = something.cover.generate_thumbnail(width=1215)
        assert something.cover.count() == 4
        x3.size == (1215, 1920)


def test_imageset_should_be_cleared(fx_session, tmp_store):
    """All previously existing images should be removed even if
    there are already same sizes of thumbnails.

    """
    with store_context(tmp_store):
        with fx_session.begin():
            some = Something(name='Issue 13')
            with open(os.path.join(sample_images_dir, 'shinji.jpg')) as shinji:
                some.cover.from_file(shinji)
            some.cover.generate_thumbnail(width=100)
            some.cover.generate_thumbnail(width=50)
            fx_session.add(some)
        shinji_500 = hashlib.md5(some.cover.original.make_blob()).digest()
        shinji_100 = hashlib.md5(
            some.cover.find_thumbnail(width=100).make_blob()
        ).digest()
        shinji_50 = hashlib.md5(
            some.cover.find_thumbnail(width=50).make_blob()
        ).digest()
        with fx_session.begin():
            with open(os.path.join(sample_images_dir, 'asuka.jpg')) as asuka:
                some.cover.from_file(asuka)
            with raises(NoResultFound):
                some.cover.find_thumbnail(width=100)
            some.cover.generate_thumbnail(width=100)
            some.cover.generate_thumbnail(width=50)
            fx_session.add(some)
        asuka_500 = hashlib.md5(some.cover.original.make_blob()).digest()
        asuka_100 = hashlib.md5(
            some.cover.find_thumbnail(width=100).make_blob()
        ).digest()
        asuka_50 = hashlib.md5(
            some.cover.find_thumbnail(width=50).make_blob()
        ).digest()
    assert shinji_500 != asuka_500
    assert shinji_100 != asuka_100
    assert shinji_50 != asuka_50