set -e

./build-rpm.sh
ag --files-with-matches -i '#!/usr/bin/python3' | xargs -I {} bash -c 'sed -i "s|#!/usr/bin/python3|#!/usr/bin/python3|" "{}"'
sudo dnf remove dictee-cuda -y
sudo rpm -ivh dictee-cuda-1.1.0-1.x86_64.rpm --nodeps
sudo dnf install ./dictee-plasmoid-1.1.0-1.noarch.rpm -y
