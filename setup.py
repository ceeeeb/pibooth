import os.path as osp
from setuptools import setup, find_packages

HERE = osp.abspath(osp.dirname(__file__))
README = osp.join(HERE, 'README.rst')
long_description = open(README, encoding='utf-8').read() if osp.isfile(README) else ''

setup(
    name='pibooth-ceeeeb',
    version='2.0.8.2',
    description='A photo booth application in pure Python for the Raspberry Pi (custom fork by ceeeeb).',
    long_description=long_description,
    long_description_content_type='text/x-rst',
    author='Vincent Verdeil, Antoine Rousseaux, Christophe (ceeeeb)',
    url='https://github.com/ceeeeb/pibooth',
    license='MIT',
    packages=find_packages(),
    include_package_data=True,
    package_data={'pibooth': ['fonts/*', 'pictures/*']},
    install_requires=[
        'Pillow==9.2.0',
        'pygame>=1.9.6',
        'pygame-menu==4.0.7',
        'pygame-vkeyboard>=2.0.8',
        'psutil>=5.5.1',
        'pluggy>=0.13.1',
        'gpiozero>=1.5.1',
    ],
    entry_points={
        'console_scripts': [
            'pibooth = pibooth.booth:main',
            'pibooth-count = pibooth.scripts.count:main',
            'pibooth-diag = pibooth.scripts.diagnostic:main',
            'pibooth-fonts = pibooth.scripts.fonts:main',
            'pibooth-printcfg = pibooth.scripts.printer:main',
            'pibooth-regen = pibooth.scripts.regenerate:main',
        ],
    },
    python_requires='>=3.7',
)
