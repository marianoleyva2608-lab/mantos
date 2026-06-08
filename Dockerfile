FROM node:18-alpine
WORKDIR /app
COPY index.html .
RUN npm install -g serve
CMD sh -c "serve -p ${PORT:-3000} -s ."
